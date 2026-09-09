import hashlib
import secrets
import time
from datetime import datetime, timedelta

import streamlit as st

from security import hash_password, validate_password, verify_password
from branding import DEFAULT_PROFILE, logo_file
from audit import record_event
from ui import apply_theme


MAX_ATTEMPTS = 5
LOCK_SECONDS = 60
SESSION_DAYS = 7
SESSION_PARAM = "session"
AUTH_STATE_KEYS = ("session_token", "user_id", "user", "role", "approval_escalation_checked")


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
    st.session_state["session_token"] = raw_token


def _restore_session(conn):
    raw_token = st.session_state.get("session_token")
    if not raw_token:
        return False
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT u.id, u.username, u.role
        FROM login_sessions s JOIN users u ON u.id=s.user_id
        WHERE s.token_hash=%s AND s.revoked=FALSE AND s.expires_at > CURRENT_TIMESTAMP AND COALESCE(u.active,TRUE)=TRUE
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


def _reject_url_session(conn):
    """URL tokens are shareable bearer credentials and must never authenticate a user."""
    raw_token = st.query_params.get(SESSION_PARAM)
    if not raw_token:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE login_sessions SET revoked=TRUE WHERE token_hash=%s", (_token_hash(raw_token),))
        conn.commit()
    except Exception:
        conn.rollback()
    for key in AUTH_STATE_KEYS:
        st.session_state.pop(key, None)
    try:
        del st.query_params[SESSION_PARAM]
    except KeyError:
        pass
    st.warning("For your security, a login session contained in a shared link was rejected. Please sign in with your own account.")
    return True


def _active_session_valid(conn):
    user_id = st.session_state.get("user_id")
    raw_token = st.session_state.get("session_token")
    if not user_id or not raw_token:
        return False
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT 1 FROM login_sessions s
        JOIN users u ON u.id=s.user_id
        WHERE s.user_id=%s AND s.token_hash=%s AND s.revoked=FALSE
          AND s.expires_at>CURRENT_TIMESTAMP AND COALESCE(u.active,TRUE)=TRUE
        """,
        (user_id, _token_hash(raw_token)),
    )
    return cursor.fetchone() is not None


def login_system(conn):
    company = st.session_state.get("company_profile", DEFAULT_PROFILE)
    apply_theme(company)
    left, centre, right = st.columns([1, 1.15, 1])
    with centre:
        logo = logo_file(company)
        if logo:
            st.image(str(logo), width=230)
        else:
            st.markdown(f"## {company['company_name']}")
        st.markdown("### Welcome back")
        st.caption(f"Sign in to {company['application_name']}.")
        with st.form("login_form"):
            username = st.text_input("Username").strip()
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)

        if submitted and _login_allowed():
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, password, role FROM users WHERE LOWER(username)=LOWER(%s) AND COALESCE(active,TRUE)=TRUE", (username,))
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
                record_event(conn, "LOGIN", "Security", "User", result[0], "User signed in successfully")
                st.rerun()
            else:
                attempts = st.session_state.get("login_attempts", 0) + 1
                st.session_state["login_attempts"] = attempts
                if attempts >= MAX_ATTEMPTS:
                    st.session_state["login_locked_until"] = time.time() + LOCK_SECONDS
                    st.session_state["login_attempts"] = 0
                st.error("The username or password is incorrect.")


def _force_password_change(conn):
    st.markdown("### Create your private password")
    st.info("You signed in with a temporary password. Choose a new password before entering the dashboard.")
    with st.form("mandatory_password_change"):
        new_password = st.text_input("New password", type="password")
        confirmation = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Set password and continue", type="primary", use_container_width=True)
    if submitted:
        error = validate_password(new_password)
        if error:
            st.error(error)
        elif new_password != confirmation:
            st.error("The two passwords do not match.")
        else:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE users SET password=%s,must_change_password=FALSE,
                   password_changed_at=CURRENT_TIMESTAMP WHERE id=%s""",
                (hash_password(new_password), st.session_state["user_id"]),
            )
            conn.commit()
            record_event(conn, "CHANGE_PASSWORD", "Security", "User", st.session_state["user_id"], "User replaced temporary password")
            st.success("Your password has been changed.")
            st.rerun()
    st.stop()


def require_login(conn):
    _reject_url_session(conn)
    if st.session_state.get("user_id") and not _active_session_valid(conn):
        for key in AUTH_STATE_KEYS:
            st.session_state.pop(key, None)
    if not st.session_state.get("user_id") and not _restore_session(conn):
        login_system(conn)
        st.stop()
    cursor = conn.cursor()
    cursor.execute("SELECT username, role, COALESCE(must_change_password,FALSE) FROM users WHERE id=%s AND COALESCE(active,TRUE)=TRUE", (st.session_state["user_id"],))
    current = cursor.fetchone()
    if not current:
        logout(conn)
    st.session_state["user"], st.session_state["role"] = current[0], current[1]
    if current[2]:
        _force_password_change(conn)


def require_role(*roles):
    if st.session_state.get("role") not in roles:
        st.error("You do not have permission to view this page.")
        st.stop()


def logout(conn=None):
    raw_token = st.session_state.get("session_token")
    if conn is not None and raw_token:
        record_event(conn, "LOGOUT", "Security", "User", st.session_state.get("user_id"), "User signed out")
        cursor = conn.cursor()
        cursor.execute("UPDATE login_sessions SET revoked=TRUE WHERE token_hash=%s", (_token_hash(raw_token),))
        conn.commit()
    st.query_params.clear()
    st.session_state.clear()
    st.rerun()
