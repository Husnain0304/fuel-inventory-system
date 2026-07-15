import streamlit as st
import hashlib


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def ensure_default_admin(conn):
    cursor = conn.cursor()
    # Safe check: Count how many users exist in the table
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]
    
    # Only create the default admin if the table is completely empty
    if user_count == 0:
        cursor.execute(
            "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
            ("admin", hash_password("admin123"), "ADMIN")
        )
        conn.commit()


def login_system(conn):
    st.title("Login")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

        if submitted:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT password, role FROM users WHERE username = %s",
                (username,)
            )
            result = cursor.fetchone()

            if result and result[0] == hash_password(password):
                st.session_state["user"] = username
                st.session_state["role"] = result[1]
                st.success("Login successful ✅")
                st.rerun()
            else:
                st.error("Invalid username or password")


def require_login(conn):
    ensure_default_admin(conn)

    if "user" not in st.session_state:
        login_system(conn)
        st.stop()
