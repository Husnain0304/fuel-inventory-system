import streamlit as st
import hashlib


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def ensure_default_admin(conn):
    with conn.cursor() as cursor:
        # PostgreSQL uses %s placeholders instead of ?
        cursor.execute("SELECT * FROM users WHERE username = %s", ("admin",))
        result = cursor.fetchone()
        
        if not result:
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
            with conn.cursor() as cursor:
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
