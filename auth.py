import time

import streamlit as st

from security import hash_password, verify_password
from ui import apply_theme


MAX_ATTEMPTS = 5
LOCK_SECONDS = 60


def _login_allowed() -> bool:
    locked_until = st.session_state.get("login_locked_until", 0)
    if locked_until > time.time():
        st.error(f"Too many attempts. Try again in {int(locked_until - time.time()) + 1} seconds.")
        return False
    return True


def login_system(conn) -> None:
    apply_theme()
    left, centre, right = st.columns([1, 1.15, 1])
    with centre:
        st.image("assets/fillit-logo.png", width=230)
        st.markdown("### Welcome back")
        st.caption("Sign in to manage fleet fuel operations.")
        with st.form("login_form"):
            username = st.text_input("Username").strip()
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)

        if submitted and _login_allowed():
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, password, role FROM users WHERE LOWER(username)=LOWER(%s)", (username,))
            result = cursor.fetchone()
            valid, needs_upgrade = verify_password(password, result[2]) if result else (False, False)
            if valid:
                if needs_upgrade:
                    cursor.execute("UPDATE users SET password=%s WHERE id=%s", (hash_password(password), result[0]))
                    conn.commit()
                st.session_state["user_id"] = result[0]
                st.session_state["user"] = result[1]
                st.session_state["role"] = result[3]
                st.session_state["login_attempts"] = 0
                st.rerun()
            else:
                attempts = st.session_state.get("login_attempts", 0) + 1
                st.session_state["login_attempts"] = attempts
                if attempts >= MAX_ATTEMPTS:
                    st.session_state["login_locked_until"] = time.time() + LOCK_SECONDS
                    st.session_state["login_attempts"] = 0
                st.error("The username or password is incorrect.")


def require_login(conn) -> None:
    user_id = st.session_state.get("user_id")
    if user_id:
        cursor = conn.cursor()
        cursor.execute("SELECT username, role FROM users WHERE id=%s", (user_id,))
        current = cursor.fetchone()
        if current:
            st.session_state["user"], st.session_state["role"] = current
            return
    for key in ("user_id", "user", "role"):
        st.session_state.pop(key, None)
    login_system(conn)
    st.stop()


def require_role(*roles: str) -> None:
    if st.session_state.get("role") not in roles:
        st.error("You do not have permission to view this page.")
        st.stop()


def logout() -> None:
    st.session_state.clear()
    st.query_params.clear()
    st.rerun()
