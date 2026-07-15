import streamlit as st
import hashlib
from sqlalchemy import text


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def ensure_default_admin(conn):
    with conn.session as session:
        # PostgreSQL uses named parameters with ':' instead of '?'
        result = session.execute(
            text("SELECT * FROM users WHERE username = :username"),
            {"username": "admin"}
        ).fetchone()
        
        if not result:
            session.execute(
                text("INSERT INTO users (username, password, role) VALUES (:username, :password, :role)"),
                {
                    "username": "admin",
                    "password": hash_password("admin123"),
                    "role": "ADMIN"
                }
            )
            session.commit()


def login_system(conn):
    st.title("Login")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

        if submitted:
            with conn.session as session:
                result = session.execute(
                    text("SELECT password, role FROM users WHERE username = :username"),
                    {"username": username}
                ).fetchone()

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
