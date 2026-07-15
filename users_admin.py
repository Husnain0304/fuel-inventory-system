import streamlit as st
import hashlib
import pandas as pd

# Uses your exact hashing method from auth.py
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def render_user_management(conn, cursor):
    st.title("👤 User Credentials Management")
    st.info("💡 Use this panel to securely create, edit, or delete user login credentials.")

    # Fetch current accounts up front so both sections can use them
    users_df = pd.read_sql_query("SELECT id, username, role FROM users ORDER BY username", conn)

    # CREATE NEW USER SECTION
    st.subheader("➕ Create New User Account")
    with st.form("create_user_form", clear_on_submit=True):
        new_username = st.text_input("Username").strip()
        new_password = st.text_input("Password", type="password")
        new_role = st.selectbox("Assign Role", ["OPERATOR", "ADMIN"])
        
        submit_btn = st.form_submit_button("Create User")
        
        if submit_btn:
            if not new_username or not new_password:
                st.error("Both username and password are required!")
            else:
                try:
                    hashed_pw = hash_password(new_password)
                    cursor.execute("""
                        INSERT INTO users (username, password, role) 
                        VALUES (%s, %s, %s)
                    """, (new_username, hashed_pw, new_role))
                    conn.commit()
                    st.success(f"Success! Account for '{new_username}' has been created. 🎉")
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error("This username is already taken. Try another one!")

    st.markdown("---")

    # EDIT EXISTING USER SECTION
    st.subheader("✏️ Edit Existing User Details")
    if users_df.empty:
        st.write("No users available to edit.")
    else:
        # Create a dropdown mapping "username (ROLE)" to the row details
        user_options = {f"{row['username']} ({row['role']})": row for _, row in users_df.iterrows()}
        selected_option = st.selectbox("Select a User to Edit", list(user_options.keys()))
        
        selected_user = user_options[selected_option]
        
        with st.form("edit_user_form"):
            st.write(f"Modifying credentials for database ID: `{selected_user['id']}`")
            edit_username = st.text_input("Edit Username", value=selected_user['username']).strip()
            edit_password = st.text_input("Enter New Password (Leave blank to keep current password)", type="password")
            edit_role = st.selectbox("Edit Role", ["OPERATOR", "ADMIN"], index=0 if selected_user['role'] == "OPERATOR" else 1)
            
            update_btn = st.form_submit_button("Save Changes")
            
            if update_btn:
                if not edit_username:
                    st.error("Username cannot be empty!")
                else:
                    try:
                        if edit_password.strip():
                            # If a new password was provided, hash it and update everything
                            hashed_pw = hash_password(edit_password)
                            cursor.execute("""
                                UPDATE users 
                                SET username = %s, password = %s, role = %s 
                                WHERE id = %s
                            """, (edit_username, hashed_pw, edit_role, selected_user['id']))
                        else:
                            # If password field is blank, only update username and role
                            cursor.execute("""
                                UPDATE users 
                                SET username = %s, role = %s 
                                WHERE id = %s
                            """, (edit_username, edit_role, selected_user['id']))
                        
                        conn.commit()
                        st.success("User configuration updated successfully! 🔄")
                        st.rerun()
                    except Exception as e:
                        conn.rollback()
                        st.error("Could not update. That username might already be in use by another account.")

    st.markdown("---")

    # VIEW AND DELETE SECTION
    st.subheader("👥 Current Accounts in System")
    if users_df.empty:
        st.warning("No registered users found.")
    else:
        for _, row in users_df.iterrows():
            user_id = row['id']
            username = row['username']
            role = row['role']
            
            c1, c2, c3 = st.columns([3, 2, 1])
            c1.write(f"👤 **{username}**")
            c2.write(f"Role: `{role}`")
            
            if username == st.session_state.get("user"):
                c3.write("*(You)*")
            else:
                if c3.button("Delete Account", key=f"del_usr_{user_id}", type="primary"):
                    cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
                    conn.commit()
                    st.success(f"Deleted user '{username}'")
                    st.rerun()
