import hashlib
import secrets
import time
from datetime import datetime, timedelta

import streamlit as st
from streamlit_cookies_controller import CookieController

from security import hash_password, verify_password
from ui import apply_theme


MAX_ATTEMPTS = 5
LOCK_SECONDS = 60
SESSION_DAYS = 7
COOKIE_NAME = "fillit_session"


@st.cache_resource(show_spinner=False)
def _cookies():
    return CookieController()


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _login_allowed():
    locked_until = st.session_state.get("login_locked_until", 0)
    if locked_until > time.time():
        st.error(f"Too many attempts. Try again in {int(locked_until - time.time()) + 1} seconds.")
        return False
    return True


def _create_session(conn, user_id):
    raw_token = secrets.token_urlsafe(32)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM login_sessions WHERE expires_at < CURRENT_TIMESTAMP OR revoked=TRUE")
    cursor.execute(
        "INSERT INTO login_sessions (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
        (user_id, _token_hash(raw_token), datetime.utcnow() + timedelta(days=SESSION_DAYS)),
    )
    conn.commit()
    _cookies().set(COOKIE_NAME, raw_token)
    st.session_state["session_token"] = raw_token


def _restore_session(conn):
    raw_token = st.session_state.get("session_token") or _cookies().get(COOKIE_NAME)
    if not raw_token:
        return False
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT u.id, u.username, u.role
        FROM login_sessions s JOIN users u ON u.id=s.user_id
        WHERE s.token_hash=%s AND s.revoked=FALSE AND s.expires_at > CURRENT_TIMESTAMP
        """,
        (_token_hash(raw_token),),
    )
    user = cursor.fetchone()
    if not user:
        return False
    st.session_state["session_token"] = raw_token
    st.session_state["user_id"] = user[0]
    st.session_state["user"] = user[1]
    st.session_state["role"] = user[2]
    return True


def login_system(conn):
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
                _create_session(conn, result[0])
                st.rerun()
            else:
                attempts = st.session_state.get("login_attempts", 0) + 1
                st.session_state["login_attempts"] = attempts
                if attempts >= MAX_ATTEMPTS:
                    st.session_state["login_locked_until"] = time.time() + LOCK_SECONDS
                    st.session_state["login_attempts"] = 0
                st.error("The username or password is incorrect.")


def require_login(conn):
    if not st.session_state.get("user_id") and not _restore_session(conn):
        login_system(conn)
        st.stop()
    cursor = conn.cursor()
    cursor.execute("SELECT username, role FROM users WHERE id=%s", (st.session_state["user_id"],))
    current = cursor.fetchone()
    if not current:
        logout(conn)
    st.session_state["user"], st.session_state["role"] = current


def require_role(*roles):
    if st.session_state.get("role") not in roles:
        st.error("You do not have permission to view this page.")
        st.stop()


def logout(conn=None):
    raw_token = st.session_state.get("session_token") or _cookies().get(COOKIE_NAME)
    if conn is not None and raw_token:
        cursor = conn.cursor()
        cursor.execute("UPDATE login_sessions SET revoked=TRUE WHERE token_hash=%s", (_token_hash(raw_token),))
        conn.commit()
    _cookies().remove(COOKIE_NAME)
    st.session_state.clear()
    st.rerun()
