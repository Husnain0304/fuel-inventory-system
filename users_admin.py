import streamlit as st
import hashlib
import pandas as pd

# Uses your exact hashing method from auth.py
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def render_user_management(conn, cursor):
    st.title("👤 User Credentials Management")
    st.info("💡 Use this panel to securely create or delete user login credentials.")

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
                    
                    # Insert user matching your exact column names
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

    st.subheader("👥 Current Accounts in System")
    
    # Query your exact table schema
    users_df = pd.read_sql_query("SELECT id, username, role FROM users ORDER BY username", conn)
    
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
            
            # Simple check to make sure you don't delete yourself
            if username == st.session_state.get("user"):
                c3.write("*(You)*")
            else:
                if c3.button("Delete Account", key=f"del_usr_{user_id}", type="primary"):
                    cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
                    conn.commit()
                    st.success(f"Deleted user '{username}'")
                    st.rerun()
