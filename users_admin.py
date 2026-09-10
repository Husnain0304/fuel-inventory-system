import re
import secrets
import string

import pandas as pd
import streamlit as st

from audit import record_event
from email_service import clean_app_url, email_is_configured, send_user_invitation
from rbac import ROLE_LABELS, ROLES, allowed_pages, ensure_rbac_schema
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


def _create_user(conn, cursor, username, email, phone, role):
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
        email.lower(), username, temporary_password, ROLE_LABELS.get(role, role),
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
    users = pd.read_sql_query(
        """SELECT id,username,email,phone_number,role,COALESCE(active,TRUE) AS active,
                  COALESCE(must_change_password,FALSE) AS must_change_password,
                  invitation_sent_at,COALESCE(invitation_status,'NOT_SENT') AS invitation_status,
                  invitation_last_error,password_changed_at FROM users ORDER BY username""", conn,
    )
    _show_invitation_result()
    tab_users, tab_matrix = st.tabs(["User accounts", "Permission matrix"])
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
                role = d.selectbox("Role", ROLES, format_func=lambda value: ROLE_LABELS[value])
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
                        _create_user(conn, cursor, username, email, phone, role)
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
            options = {f"{row.username} · {ROLE_LABELS.get(row.role,row.role)} · {'Active' if row.active else 'Inactive'}": row for row in users.itertuples()}
            account = options[st.selectbox("Manage account", list(options))]
            account_email = str(account.email).strip() if pd.notna(account.email) else ""
            account_phone = str(account.phone_number).strip() if pd.notna(account.phone_number) else ""
            with st.form("edit_user_v3"):
                a, b = st.columns(2)
                new_username = a.text_input("Username", value=account.username).strip()
                new_email = b.text_input("Email address", value=account_email).strip()
                c, d = st.columns(2)
                new_phone = c.text_input("Phone number", value=account_phone).strip()
                new_role = d.selectbox("Role", ROLES, index=ROLES.index(account.role) if account.role in ROLES else 0, format_func=lambda value: ROLE_LABELS[value])
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
                        sent, message = send_user_invitation(account_email, account.username, temporary_password, ROLE_LABELS.get(account.role, account.role), company.get("company_name", "Company"), company.get("application_name", "Fuel Inventory Control"))
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
    with tab_matrix:
        rows = []
        for role in ROLES:
            pages = allowed_pages(role)
            rows.append({"Role": ROLE_LABELS[role], "Accessible workspaces": len(pages), "Workspace access": ", ".join(sorted(pages))})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=420)
        st.info("Administrators retain unrestricted access. The legacy Operator role remains available for existing accounts.")
