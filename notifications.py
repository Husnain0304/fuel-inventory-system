import pandas as pd
import streamlit as st

from ui import page_header


def ensure_notification_schema(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("""CREATE TABLE IF NOT EXISTS user_notifications(
            id BIGSERIAL PRIMARY KEY, recipient_username TEXT, recipient_group TEXT,
            notification_type TEXT NOT NULL, title TEXT NOT NULL, message TEXT NOT NULL,
            source_type TEXT, source_id TEXT, target_page TEXT DEFAULT 'Approvals',
            is_read BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            read_at TIMESTAMPTZ, created_by TEXT)""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON user_notifications(recipient_username,is_read,created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_group ON user_notifications(recipient_group,is_read,created_at DESC)")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def notify_user(conn, username, title, message, notification_type="INFO", source_type=None,
                source_id=None, target_page="Approvals", created_by="System"):
    if not username:
        return None
    cursor = conn.cursor()
    cursor.execute("""INSERT INTO user_notifications
        (recipient_username,notification_type,title,message,source_type,source_id,target_page,created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (username, notification_type, title, message, source_type,
         str(source_id) if source_id is not None else None, target_page, created_by))
    notification_id = cursor.fetchone()[0]
    conn.commit()
    return notification_id


def notify_approval_team(conn, title, message, source_type=None, source_id=None, created_by="System"):
    cursor = conn.cursor()
    cursor.execute("""SELECT username FROM users
        WHERE role IN ('ADMIN','INVENTORY_MANAGER','APPROVER') AND LOWER(username)<>LOWER(%s)""", (created_by,))
    recipients = [row[0] for row in cursor.fetchall()]
    notification_id = None
    for username in recipients:
        cursor.execute("""INSERT INTO user_notifications
            (recipient_username,notification_type,title,message,source_type,source_id,target_page,created_by)
            VALUES (%s,'APPROVAL_REQUIRED',%s,%s,%s,%s,'Approvals',%s) RETURNING id""",
            (username, title, message, source_type,
             str(source_id) if source_id is not None else None, created_by))
        notification_id = cursor.fetchone()[0]
    conn.commit()
    return notification_id


def _audience():
    role = st.session_state.get("role", "VIEWER")
    username = st.session_state.get("user", "")
    return username, role in ("ADMIN", "INVENTORY_MANAGER", "APPROVER")


def unread_count(conn):
    ensure_notification_schema(conn)
    username, approval_member = _audience()
    cursor = conn.cursor()
    cursor.execute("""SELECT COUNT(*) FROM user_notifications WHERE is_read=FALSE
        AND (LOWER(recipient_username)=LOWER(%s) OR (recipient_group='APPROVAL_TEAM' AND %s))""",
        (username, approval_member))
    return int(cursor.fetchone()[0])


def _mark_read(conn, notification_id=None):
    username, approval_member = _audience()
    cursor = conn.cursor()
    scope = "(LOWER(recipient_username)=LOWER(%s) OR (recipient_group='APPROVAL_TEAM' AND %s))"
    if notification_id is None:
        cursor.execute(f"UPDATE user_notifications SET is_read=TRUE,read_at=CURRENT_TIMESTAMP WHERE is_read=FALSE AND {scope}",
                       (username, approval_member))
    else:
        cursor.execute(f"UPDATE user_notifications SET is_read=TRUE,read_at=CURRENT_TIMESTAMP WHERE id=%s AND {scope}",
                       (notification_id, username, approval_member))
    conn.commit()


def render_notifications(conn):
    ensure_notification_schema(conn)
    page_header("Notification Centre", "Follow approval requests, decisions and actions requiring your attention.")
    username, approval_member = _audience()
    data = pd.read_sql_query("""SELECT id,notification_type,title,message,source_type,source_id,target_page,
        is_read,created_at,created_by FROM user_notifications
        WHERE LOWER(recipient_username)=LOWER(%s) OR (recipient_group='APPROVAL_TEAM' AND %s)
        ORDER BY is_read,created_at DESC,id DESC LIMIT 500""", conn, params=[username, approval_member])
    unread = int((~data["is_read"]).sum()) if not data.empty else 0
    a, b, c = st.columns([1, 1, 3])
    a.metric("Unread", unread)
    b.metric("All notifications", len(data))
    if c.button("Mark all as read", disabled=unread == 0, use_container_width=True):
        _mark_read(conn)
        st.rerun()
    show = st.radio("Show", ["Unread", "All"], horizontal=True)
    view = data[~data["is_read"]] if show == "Unread" and not data.empty else data
    if view.empty:
        st.success("You have no unread notifications." if show == "Unread" else "No notifications yet.")
    for item in view.itertuples():
        icon = "✓" if item.notification_type == "APPROVED" else ("✕" if item.notification_type == "REJECTED" else "!")
        with st.container(border=True):
            left, right = st.columns([5, 1])
            left.markdown(f"### {icon} {item.title}")
            left.write(item.message)
            source = f" · {item.source_type} {item.source_id}" if item.source_id else ""
            left.caption(f"{pd.to_datetime(item.created_at):%d %b %Y %H:%M} · By {item.created_by or 'System'}{source}")
            if not item.is_read and right.button("Mark read", key=f"read_{item.id}", use_container_width=True):
                _mark_read(conn, int(item.id))
                st.rerun()
            if item.target_page and right.button("Open", key=f"open_{item.id}", use_container_width=True):
                _mark_read(conn, int(item.id))
                st.session_state["navigation_target"] = item.target_page
                st.rerun()
