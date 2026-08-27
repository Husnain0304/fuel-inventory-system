import pandas as pd
import streamlit as st
from audit import record_event
from rbac import ROLE_LABELS,ROLES,allowed_pages,ensure_rbac_schema
from security import hash_password,validate_password,validate_username
from ui import page_header

def render_user_management(conn,cursor):
 ensure_rbac_schema(conn); page_header("User Access & Permissions","Create accounts, assign professional roles and review their workspace access.")
 users=pd.read_sql_query("SELECT id,username,role,COALESCE(active,TRUE) AS active FROM users ORDER BY username",conn)
 tab_users,tab_matrix=st.tabs(["User accounts","Permission matrix"])
 with tab_users:
  with st.expander("Create new user",expanded=users.empty):
   with st.form("create_user_v2",clear_on_submit=True):
    a,b=st.columns(2); username=a.text_input("Username").strip(); role=b.selectbox("Role",ROLES,format_func=lambda x:ROLE_LABELS[x]); password=st.text_input("Temporary password",type="password"); submit=st.form_submit_button("Create user",type="primary")
   if submit:
    error=validate_username(username) or validate_password(password)
    if error: st.error(error)
    else:
     try:
      cursor.execute("INSERT INTO users(username,password,role) VALUES (%s,%s,%s) RETURNING id",(username,hash_password(password),role)); user_id=cursor.fetchone()[0]; conn.commit(); record_event(conn,"CREATE_USER","Security","User",user_id,f"Created {username} with role {role}"); st.success("User created successfully."); st.rerun()
     except Exception as exc: conn.rollback(); st.error("Username already exists or the account could not be created.")
  if users.empty: st.info("No users found.")
  else:
   display=users.copy(); display["status"]=display.active.map({True:"ACTIVE",False:"INACTIVE"}); st.dataframe(display.rename(columns={"username":"Username","role":"Role","status":"Status"}).drop(columns=["active"]),use_container_width=True,hide_index=True)
   options={f"{r.username} · {ROLE_LABELS.get(r.role,r.role)} · {'Active' if r.active else 'Inactive'}":r for r in users.itertuples()}; selected=st.selectbox("Manage account",list(options)); account=options[selected]
   with st.form("edit_user_v2"):
    a,b=st.columns(2); new_username=a.text_input("Username",value=account.username).strip(); new_role=b.selectbox("Role",ROLES,index=ROLES.index(account.role) if account.role in ROLES else 0,format_func=lambda x:ROLE_LABELS[x]); new_password=st.text_input("New password (leave blank to keep current)",type="password"); save=st.form_submit_button("Save account changes",type="primary")
   if save:
    error=validate_username(new_username) or (validate_password(new_password) if new_password else None)
    if error: st.error(error)
    elif account.username==st.session_state.get("user") and new_role!="ADMIN": st.error("You cannot remove your own Administrator role. Assign another administrator first.")
    else:
     try:
      if new_password: cursor.execute("UPDATE users SET username=%s,password=%s,role=%s WHERE id=%s",(new_username,hash_password(new_password),new_role,account.id))
      else: cursor.execute("UPDATE users SET username=%s,role=%s WHERE id=%s",(new_username,new_role,account.id))
      if account.role!=new_role: cursor.execute("INSERT INTO security_role_changes(user_id,old_role,new_role,changed_by) VALUES (%s,%s,%s,%s)",(account.id,account.role,new_role,st.session_state.get("user","System")))
      conn.commit(); record_event(conn,"UPDATE_USER","Security","User",account.id,f"Updated {new_username}; role {new_role}"); st.success("Account updated."); st.rerun()
     except Exception: conn.rollback(); st.error("Account could not be updated.")
   if account.username!=st.session_state.get("user"):
    action="Deactivate" if account.active else "Reactivate"; confirm=st.checkbox(f"Confirm {action.lower()} for {account.username}")
    if st.button(f"{action} selected account",disabled=not confirm):
     new_active=not bool(account.active); cursor.execute("UPDATE users SET active=%s WHERE id=%s",(new_active,account.id))
     if not new_active: cursor.execute("UPDATE login_sessions SET revoked=TRUE WHERE user_id=%s",(account.id,))
     conn.commit(); record_event(conn,f"{action.upper()}_USER","Security","User",account.id,f"{action}d {account.username}",severity="WARNING" if not new_active else "INFO"); st.success(f"Account {action.lower()}d."); st.rerun()
 with tab_matrix:
  rows=[]
  for role in ROLES:
   pages=allowed_pages(role); rows.append({"Role":ROLE_LABELS[role],"Accessible workspaces":len(pages),"Workspace access":", ".join(sorted(pages))})
  st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True,height=420)
  st.info("Administrators retain unrestricted access. The legacy Operator role remains available for existing accounts.")
