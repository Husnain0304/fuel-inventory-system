import re
import secrets
import string

import pandas as pd
import streamlit as st

from audit import record_event
from email_service import clean_app_url, email_is_configured, send_user_invitation
from rbac import (ALL_ACTIONS, ALL_PAGES, ROLE_LABELS, ensure_rbac_schema,
                  role_catalog, role_code, role_permissions)
from security import hash_password, validate_username


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _temporary_password(length=14):
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in password) and any(c.isupper() for c in password) and any(c.isdigit() for c in password):
            return password


def _show_invitation_result():
    invitation = st.session_state.pop("new_user_invitation", None)
    if not invitation:
        return
    if invitation["sent"]:
        st.success(f"Account created and invitation sent to {invitation['email']}.")
    else:
        st.warning(f"Account created, but the email was not sent. {invitation['message']}")
        st.caption("Copy these details and send them securely to the user:")
        st.code(
            f"Sign-in link: {invitation['url']}\nUsername: {invitation['username']}\n"
            f"Temporary password: {invitation['temporary_password']}", language=None,
        )


def _create_user(conn, cursor, username, email, phone, role, role_label=None):
    temporary_password = _temporary_password()
    cursor.execute(
        """INSERT INTO users(username,password,role,email,phone_number,must_change_password)
           VALUES (%s,%s,%s,%s,%s,TRUE) RETURNING id""",
        (username, hash_password(temporary_password), role, email.lower(), phone or None),
    )
    user_id = cursor.fetchone()[0]
    conn.commit()
    company = st.session_state.get("company_profile", {})
    sent, message = send_user_invitation(
        email.lower(), username, temporary_password, role_label or ROLE_LABELS.get(role, role),
        company.get("company_name", "Company"), company.get("application_name", "Fuel Inventory Control"),
    )
    if sent:
        cursor.execute("UPDATE users SET invitation_sent_at=CURRENT_TIMESTAMP,invitation_status='SENT',invitation_last_error=NULL WHERE id=%s", (user_id,))
    else:
        cursor.execute("UPDATE users SET invitation_status='MANUAL_REQUIRED',invitation_last_error=%s WHERE id=%s", (message, user_id))
    conn.commit()
    record_event(conn, "CREATE_USER", "Security", "User", user_id,
                 f"Created {username} with role {role}; invitation {'sent' if sent else 'requires manual delivery'}")
    st.session_state["new_user_invitation"] = {
        "sent": sent, "message": message, "email": email.lower(), "username": username,
        "temporary_password": temporary_password, "url": clean_app_url(),
    }


def render_user_management(conn, cursor):
    ensure_rbac_schema(conn)
    role_rows = role_catalog(conn)
    role_labels = {row[0]: row[1] for row in role_rows}
    role_codes = list(role_labels)
    users = pd.read_sql_query(
        """SELECT id,username,email,phone_number,role,COALESCE(active,TRUE) AS active,
                  COALESCE(must_change_password,FALSE) AS must_change_password,
                  invitation_sent_at,COALESCE(invitation_status,'NOT_SENT') AS invitation_status,
                  invitation_last_error,password_changed_at FROM users ORDER BY username""", conn,
    )
    _show_invitation_result()
    tab_users, tab_roles, tab_individual, tab_matrix = st.tabs(["User accounts", "Role manager", "Individual access", "Permission matrix"])
    with tab_users:
        active_total = int(users["active"].sum()) if not users.empty else 0
        setup_pending = int(users["must_change_password"].sum()) if not users.empty else 0
        invitation_attention = int((users["invitation_status"] == "MANUAL_REQUIRED").sum()) if not users.empty else 0
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total accounts", len(users))
        m2.metric("Active", active_total)
        m3.metric("Password setup pending", setup_pending)
        m4.metric("Invitation attention", invitation_attention)
        if email_is_configured():
            st.success("Automatic invitation email is configured and ready.")
        else:
            st.info("Email delivery is not configured yet. The account can still be created and its invitation will be shown for secure manual sharing.")
        with st.expander("Create and invite a new user", expanded=users.empty):
            with st.form("create_user_v3", clear_on_submit=True):
                a, b = st.columns(2)
                username = a.text_input("Username", placeholder="e.g. ahmed.khan").strip()
                email = b.text_input("Email address", placeholder="name@company.com").strip()
                c, d = st.columns(2)
                phone = c.text_input("Phone number", placeholder="e.g. +971 50 123 4567").strip()
                role = d.selectbox("Role", role_codes, format_func=lambda value: role_labels[value])
                st.caption("A temporary password will be generated automatically. The user must replace it after first login.")
                submit = st.form_submit_button("Create account and send invitation", type="primary", use_container_width=True)
            if submit:
                error = validate_username(username)
                if error:
                    st.error(error)
                elif not EMAIL_PATTERN.fullmatch(email):
                    st.error("Enter a valid email address.")
                else:
                    try:
                        _create_user(conn, cursor, username, email, phone, role, role_labels.get(role, role))
                        st.rerun()
                    except Exception:
                        conn.rollback()
                        st.error("The username or email is already registered, or the account could not be created.")
        if users.empty:
            st.info("No users found.")
        else:
            filter_status = st.segmented_control("Show accounts", ["All", "Active", "Inactive", "Setup pending"], default="All")
            filtered_users = users
            if filter_status == "Active": filtered_users = users[users["active"]]
            elif filter_status == "Inactive": filtered_users = users[~users["active"]]
            elif filter_status == "Setup pending": filtered_users = users[users["must_change_password"]]
            display = users.copy()
            display["status"] = display["active"].map({True: "ACTIVE", False: "INACTIVE"})
            display["password_status"] = display["must_change_password"].map({True: "CHANGE REQUIRED", False: "COMPLETE"})
            display = display[display["id"].isin(filtered_users["id"])]
            st.dataframe(display[["username", "email", "phone_number", "role", "status", "password_status", "invitation_status", "invitation_sent_at", "password_changed_at"]],
                         use_container_width=True, hide_index=True, height=390,
                         column_config={"username": "Username", "email": "Email", "phone_number": "Phone", "role": "Role", "status": "Account", "password_status": "Password setup", "invitation_status": "Invitation", "invitation_sent_at": "Last sent", "password_changed_at": "Password changed"})
            options = {f"{row.username} · {role_labels.get(row.role, ROLE_LABELS.get(row.role,row.role))} · {'Active' if row.active else 'Inactive'}": row for row in users.itertuples()}
            account = options[st.selectbox("Manage account", list(options))]
            account_email = str(account.email).strip() if pd.notna(account.email) else ""
            account_phone = str(account.phone_number).strip() if pd.notna(account.phone_number) else ""
            with st.form("edit_user_v3"):
                a, b = st.columns(2)
                new_username = a.text_input("Username", value=account.username).strip()
                new_email = b.text_input("Email address", value=account_email).strip()
                c, d = st.columns(2)
                new_phone = c.text_input("Phone number", value=account_phone).strip()
                new_role = d.selectbox("Role", role_codes, index=role_codes.index(account.role) if account.role in role_codes else 0, format_func=lambda value: role_labels[value])
                save = st.form_submit_button("Save account details", type="primary", use_container_width=True)
            if save:
                error = validate_username(new_username)
                if error:
                    st.error(error)
                elif not EMAIL_PATTERN.fullmatch(new_email):
                    st.error("Enter a valid email address.")
                elif account.username == st.session_state.get("user") and new_role != "ADMIN":
                    st.error("You cannot remove your own Administrator role. Assign another administrator first.")
                else:
                    try:
                        cursor.execute("UPDATE users SET username=%s,email=%s,phone_number=%s,role=%s WHERE id=%s", (new_username, new_email.lower(), new_phone or None, new_role, account.id))
                        if account.role != new_role:
                            cursor.execute("INSERT INTO security_role_changes(user_id,old_role,new_role,changed_by) VALUES (%s,%s,%s,%s)", (account.id, account.role, new_role, st.session_state.get("user", "System")))
                        conn.commit()
                        record_event(conn, "UPDATE_USER", "Security", "User", account.id, f"Updated {new_username}; role {new_role}")
                        st.success("Account details updated.")
                        st.rerun()
                    except Exception:
                        conn.rollback()
                        st.error("Account could not be updated.")
            with st.expander("Reset password and resend invitation"):
                st.warning("This creates a new temporary password, signs the user out everywhere and requires a new private password after login.")
                confirm_reset = st.checkbox(f"Confirm password reset for {account.username}")
                if st.button("Reset password and send invitation", disabled=not confirm_reset, type="primary"):
                    if not account_email:
                        st.error("Add an email address to this account first.")
                    else:
                        temporary_password = _temporary_password()
                        cursor.execute("UPDATE users SET password=%s,must_change_password=TRUE,password_changed_at=NULL WHERE id=%s", (hash_password(temporary_password), account.id))
                        cursor.execute("UPDATE login_sessions SET revoked=TRUE WHERE user_id=%s", (account.id,))
                        conn.commit()
                        company = st.session_state.get("company_profile", {})
                        sent, message = send_user_invitation(account_email, account.username, temporary_password, role_labels.get(account.role, ROLE_LABELS.get(account.role, account.role)), company.get("company_name", "Company"), company.get("application_name", "Fuel Inventory Control"))
                        if sent:
                            cursor.execute("UPDATE users SET invitation_sent_at=CURRENT_TIMESTAMP,invitation_status='SENT',invitation_last_error=NULL WHERE id=%s", (account.id,))
                        else:
                            cursor.execute("UPDATE users SET invitation_status='MANUAL_REQUIRED',invitation_last_error=%s WHERE id=%s", (message, account.id))
                        conn.commit()
                        record_event(conn, "RESET_USER_PASSWORD", "Security", "User", account.id, f"Issued temporary password; invitation {'sent' if sent else 'requires manual delivery'}", severity="WARNING")
                        if sent:
                            st.success("A new temporary password was emailed to the user.")
                        else:
                            st.warning(message)
                            st.code(f"Sign-in link: {clean_app_url()}\nUsername: {account.username}\nTemporary password: {temporary_password}", language=None)
            if account.username != st.session_state.get("user"):
                action = "Deactivate" if account.active else "Reactivate"
                confirm = st.checkbox(f"Confirm {action.lower()} for {account.username}")
                if st.button(f"{action} selected account", disabled=not confirm):
                    new_active = not bool(account.active)
                    cursor.execute("UPDATE users SET active=%s WHERE id=%s", (new_active, account.id))
                    if not new_active:
                        cursor.execute("UPDATE login_sessions SET revoked=TRUE WHERE user_id=%s", (account.id,))
                    conn.commit()
                    record_event(conn, f"{action.upper()}_USER", "Security", "User", account.id, f"{action}d {account.username}", severity="WARNING" if not new_active else "INFO")
                    st.success(f"Account {action.lower()}d.")
                    st.rerun()
    with tab_roles:
        st.subheader("Create a reusable role")
        with st.form("create_custom_role"):
            left, right = st.columns(2)
            new_role_name = left.text_input("Role designation", placeholder="e.g. Depot Supervisor")
            copy_from = right.selectbox("Start with permissions from", [""] + role_codes, format_func=lambda value: "No access — start empty" if not value else role_labels[value])
            new_description = st.text_input("Description", placeholder="What this role is responsible for")
            create_role = st.form_submit_button("Create role", type="primary", use_container_width=True)
        if create_role:
            code = role_code(new_role_name)
            if len(new_role_name.strip()) < 3 or not code:
                st.error("Enter a clear role designation.")
            else:
                try:
                    cursor.execute("INSERT INTO security_roles(role_code,role_name,description,created_by) VALUES(%s,%s,%s,%s)", (code, new_role_name.strip(), new_description.strip(), st.session_state.get("user")))
                    if copy_from:
                        base_pages, base_actions = role_permissions(conn, copy_from)
                        for item in base_pages: cursor.execute("INSERT INTO security_role_pages(role_code,page_name) VALUES(%s,%s)", (code, item))
                        for item in base_actions: cursor.execute("INSERT INTO security_role_actions(role_code,action_name) VALUES(%s,%s)", (code, item))
                    conn.commit(); record_event(conn, "CREATE_ROLE", "Security", "Role", code, f"Created role {new_role_name.strip()}")
                    st.success("Role created. You can now adjust its access below."); st.rerun()
                except Exception:
                    conn.rollback(); st.error("That role designation already exists or could not be created.")

        st.subheader("Design role permissions")
        selected_role = st.selectbox("Select role", role_codes, format_func=lambda value: role_labels[value], key="role_permission_editor")
        selected_pages, selected_actions = role_permissions(conn, selected_role)
        role_record = next(row for row in role_rows if row[0] == selected_role)
        if selected_role == "ADMIN":
            st.info("Administrator is protected and always has full access.")
        pages = st.multiselect("Pages this role can open", sorted(ALL_PAGES), default=sorted(selected_pages), disabled=selected_role == "ADMIN")
        actions = st.multiselect("Actions this role can perform", sorted(ALL_ACTIONS), default=sorted(selected_actions), disabled=selected_role == "ADMIN")
        if st.button("Save role permissions", type="primary", use_container_width=True, disabled=selected_role == "ADMIN"):
            pages = set(pages) | {"Command Centre"}
            cursor.execute("DELETE FROM security_role_pages WHERE role_code=%s", (selected_role,))
            cursor.execute("DELETE FROM security_role_actions WHERE role_code=%s", (selected_role,))
            for item in pages: cursor.execute("INSERT INTO security_role_pages(role_code,page_name) VALUES(%s,%s)", (selected_role, item))
            for item in actions: cursor.execute("INSERT INTO security_role_actions(role_code,action_name) VALUES(%s,%s)", (selected_role, item))
            cursor.execute("UPDATE security_roles SET updated_at=CURRENT_TIMESTAMP WHERE role_code=%s", (selected_role,))
            conn.commit(); record_event(conn, "UPDATE_ROLE_PERMISSIONS", "Security", "Role", selected_role, f"Saved {len(pages)} pages and {len(actions)} actions")
            st.success("Role permissions saved. Users receive the change on their next page refresh.")
        if not role_record[3]:
            assigned = int(pd.read_sql_query("SELECT COUNT(*) AS total FROM users WHERE role=%s AND COALESCE(active,TRUE)=TRUE", conn, params=[selected_role]).iloc[0, 0])
            confirm_archive = st.checkbox(f"Confirm deactivation of {role_labels[selected_role]}")
            if st.button("Deactivate custom role", disabled=not confirm_archive or assigned > 0):
                cursor.execute("UPDATE security_roles SET active=FALSE,updated_at=CURRENT_TIMESTAMP WHERE role_code=%s", (selected_role,)); conn.commit()
                record_event(conn, "DEACTIVATE_ROLE", "Security", "Role", selected_role, f"Deactivated {role_labels[selected_role]}"); st.rerun()
            if assigned: st.caption(f"Move {assigned} active user(s) to another role before deactivating this role.")

    with tab_individual:
        st.subheader("Additional or removed access for one user")
        st.caption("Individual settings override the assigned role. Leave both lists empty to use only the role permissions.")
        user_options = {f"{row.username} · {role_labels.get(row.role,row.role)}": row for row in users.itertuples()}
        target = user_options[st.selectbox("Select user", list(user_options), key="override_user")]
        if target.role == "ADMIN":
            st.info("Administrator access is protected and cannot be restricted.")
        else:
            base_pages, base_actions = role_permissions(conn, target.role)
            override_rows = pd.read_sql_query("SELECT permission_type,permission_name,effect FROM security_user_overrides WHERE user_id=%s", conn, params=[target.id])
            def current(kind, effect):
                if override_rows.empty: return []
                return sorted(override_rows[(override_rows["permission_type"] == kind) & (override_rows["effect"] == effect)]["permission_name"].tolist())
            p1, p2 = st.columns(2)
            available_add_pages, available_remove_pages = ALL_PAGES - base_pages, base_pages - {"Command Centre"}
            add_pages = p1.multiselect("Additional pages", sorted(available_add_pages), default=sorted(set(current("PAGE", "ALLOW")) & available_add_pages))
            remove_pages = p2.multiselect("Remove pages", sorted(available_remove_pages), default=sorted(set(current("PAGE", "DENY")) & available_remove_pages))
            a1, a2 = st.columns(2)
            available_add_actions, available_remove_actions = ALL_ACTIONS - base_actions, base_actions
            add_actions = a1.multiselect("Additional actions", sorted(available_add_actions), default=sorted(set(current("ACTION", "ALLOW")) & available_add_actions))
            remove_actions = a2.multiselect("Remove actions", sorted(available_remove_actions), default=sorted(set(current("ACTION", "DENY")) & available_remove_actions))
            if st.button("Save individual access", type="primary", use_container_width=True):
                cursor.execute("DELETE FROM security_user_overrides WHERE user_id=%s", (target.id,))
                for kind, effect, items in (("PAGE", "ALLOW", add_pages), ("PAGE", "DENY", remove_pages), ("ACTION", "ALLOW", add_actions), ("ACTION", "DENY", remove_actions)):
                    for item in items:
                        cursor.execute("INSERT INTO security_user_overrides(user_id,permission_type,permission_name,effect,updated_by) VALUES(%s,%s,%s,%s,%s)", (target.id, kind, item, effect, st.session_state.get("user")))
                conn.commit(); record_event(conn, "UPDATE_USER_PERMISSIONS", "Security", "User", target.id, f"Saved individual access overrides for {target.username}")
                st.success("Individual access saved. It will apply when the user refreshes the app.")
            if st.button("Clear all individual overrides", use_container_width=True):
                cursor.execute("DELETE FROM security_user_overrides WHERE user_id=%s", (target.id,)); conn.commit()
                record_event(conn, "CLEAR_USER_PERMISSIONS", "Security", "User", target.id, f"Cleared overrides for {target.username}"); st.rerun()

    with tab_matrix:
        rows = []
        for role, label in role_labels.items():
            pages, actions = role_permissions(conn, role)
            rows.append({"Role": label, "Accessible workspaces": len(pages), "Allowed actions": len(actions), "Workspace access": ", ".join(sorted(pages))})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=420)
        st.info("Administrators retain unrestricted access. The legacy Operator role remains available for existing accounts.")
