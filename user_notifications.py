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
        cursor.execute("""CREATE TABLE IF NOT EXISTS approval_request_messages(
            id BIGSERIAL PRIMARY KEY,request_id BIGINT NOT NULL REFERENCES approval_requests(id) ON DELETE CASCADE,
            message_type TEXT NOT NULL CHECK(message_type IN ('FOLLOW_UP','APPROVER_RESPONSE','WITHDRAWAL')),
            message TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_request_messages_request ON approval_request_messages(request_id,created_at,id)")
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


def set_request_confirmation(request_id, title):
    st.session_state["request_confirmation"]={"id":int(request_id),"title":title}


def render_request_confirmation():
    item=st.session_state.get("request_confirmation")
    if not item:
        return
    left,right=st.columns([8,1])
    left.success(f"AP-{item['id']} successfully submitted and waiting for approval. {item['title']}")
    if right.button("Dismiss",key="dismiss_request_confirmation",use_container_width=True):
        st.session_state.pop("request_confirmation",None)
        st.rerun()


def request_messages(conn,request_id):
    return pd.read_sql_query("""SELECT message_type,message,created_by,created_at
        FROM approval_request_messages WHERE request_id=%s ORDER BY created_at,id""",conn,params=[request_id])


def add_request_message(conn,request_id,message_type,message,created_by):
    cursor=conn.cursor(); cursor.execute("""INSERT INTO approval_request_messages
        (request_id,message_type,message,created_by) VALUES (%s,%s,%s,%s) RETURNING id""",
        (request_id,message_type,message.strip(),created_by))
    message_id=cursor.fetchone()[0]; conn.commit(); return message_id


def _audience():
    role = st.session_state.get("role", "VIEWER")
    username = st.session_state.get("user", "")
    return username, role in ("ADMIN", "INVENTORY_MANAGER", "APPROVER")


def unread_count(conn):
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


def _render_inbox(conn):
    username, approval_member = _audience()
    data = pd.read_sql_query("""SELECT id,notification_type,title,message,source_type,source_id,target_page,
        is_read,created_at,created_by FROM user_notifications
        WHERE LOWER(recipient_username)=LOWER(%s) OR (recipient_group='APPROVAL_TEAM' AND %s)
        ORDER BY is_read,created_at DESC,id DESC LIMIT 500""", conn, params=[username, approval_member])
    unread = int((~data["is_read"]).sum()) if not data.empty else 0
    a, b, c = st.columns([1, 1, 3]); a.metric("Unread", unread); b.metric("All notifications", len(data))
    if c.button("Mark all as read", disabled=unread == 0, use_container_width=True):
        _mark_read(conn); st.rerun()
    show = st.radio("Show", ["Unread", "All"], horizontal=True)
    view = data[~data["is_read"]] if show == "Unread" and not data.empty else data
    if view.empty: st.success("You have no unread notifications." if show == "Unread" else "No notifications yet.")
    for item in view.itertuples():
        icon = "✓" if item.notification_type == "APPROVED" else ("✕" if item.notification_type == "REJECTED" else "!")
        with st.container(border=True):
            left, right = st.columns([5, 1]); left.markdown(f"### {icon} {item.title}"); left.write(item.message)
            source = f" · {item.source_type} {item.source_id}" if item.source_id else ""
            left.caption(f"{pd.to_datetime(item.created_at):%d %b %Y %H:%M} · By {item.created_by or 'System'}{source}")
            if not item.is_read and right.button("Mark read", key=f"read_{item.id}", use_container_width=True):
                _mark_read(conn, int(item.id)); st.rerun()
            if item.target_page and right.button("Open", key=f"open_{item.id}", use_container_width=True):
                _mark_read(conn, int(item.id)); st.session_state["navigation_target"] = item.target_page; st.rerun()


def _render_my_requests(conn):
    username=st.session_state.get("user","")
    data=pd.read_sql_query("""SELECT id,request_kind,title,quantity,monetary_value,status,requested_at,
        reviewed_by,reviewed_at,review_comment,posted_reference,failure_message
        FROM approval_requests WHERE LOWER(requested_by)=LOWER(%s) ORDER BY requested_at DESC,id DESC""",conn,params=[username])
    if data.empty: st.info("You have not submitted any AP requests yet."); return
    a,b,c=st.columns([1,1,2]); status_filter=a.selectbox("Status",["All","PENDING","POSTED","REJECTED","CANCELLED","FAILED"]); search=b.text_input("AP number"); kind_filter=c.multiselect("Request type",sorted(data["request_kind"].unique()))
    view=data.copy()
    if status_filter!="All": view=view[view["status"]==status_filter]
    if search.strip():
        number=search.upper().replace("AP-","").strip(); view=view[view["id"]==int(number)] if number.isdigit() else view.iloc[0:0]
    if kind_filter: view=view[view["request_kind"].isin(kind_filter)]
    if view.empty: st.info("No requests match the selected filters."); return
    for item in view.itertuples():
        with st.container(border=True):
            h1,h2=st.columns([5,1]); h1.markdown(f"### AP-{item.id} · {item.title}"); h2.markdown(f"**{item.status}**")
            h1.caption(f"Submitted {pd.to_datetime(item.requested_at):%d %b %Y %H:%M} · {str(item.request_kind).replace('_',' ').title()}")
            if h2.button("Open approval",key=f"my_open_{item.id}",use_container_width=True): st.session_state["navigation_target"]="Approvals"; st.rerun()
            if item.posted_reference: st.success(f"Completed as {item.posted_reference}")
            if item.reviewed_by: st.write(f"**Reviewed by:** {item.reviewed_by}  |  **Comment:** {item.review_comment or '—'}")
            if item.failure_message: st.error(item.failure_message)
            messages=request_messages(conn,int(item.id))
            with st.expander(f"Timeline · {1+len(messages)+(1 if item.reviewed_at else 0)} events"):
                st.write(f"**Submitted** · {pd.to_datetime(item.requested_at):%d %b %Y %H:%M} · {username}")
                for message in messages.itertuples():
                    st.write(f"**{str(message.message_type).replace('_',' ').title()}** · {pd.to_datetime(message.created_at):%d %b %Y %H:%M} · {message.created_by}"); st.caption(message.message)
                if item.reviewed_at: st.write(f"**{item.status.title()}** · {pd.to_datetime(item.reviewed_at):%d %b %Y %H:%M} · {item.reviewed_by}")
            if item.status=="PENDING":
                follow,withdraw=st.tabs(["Send follow-up","Withdraw request"])
                with follow:
                    follow_text=st.text_area("Follow-up message",key=f"follow_text_{item.id}")
                    if st.button("Send follow-up",key=f"follow_send_{item.id}",type="primary"):
                        if len(follow_text.strip())<3: st.error("Enter a follow-up message.")
                        else:
                            add_request_message(conn,int(item.id),"FOLLOW_UP",follow_text,username); notify_approval_team(conn,f"Follow-up received · AP-{item.id}",follow_text,item.request_kind,item.id,username); st.success("Follow-up sent to the approval team."); st.rerun()
                with withdraw:
                    reason=st.text_area("Withdrawal reason",key=f"withdraw_reason_{item.id}")
                    if st.button("Withdraw pending request",key=f"withdraw_{item.id}"):
                        if len(reason.strip())<5: st.error("Enter a clear withdrawal reason.")
                        else:
                            cursor=conn.cursor(); cursor.execute("""UPDATE approval_requests SET status='CANCELLED',reviewed_at=CURRENT_TIMESTAMP,review_comment=%s
                                WHERE id=%s AND status='PENDING' AND LOWER(requested_by)=LOWER(%s)""",(reason.strip(),int(item.id),username))
                            if cursor.rowcount!=1: conn.rollback(); st.error("This request is no longer available for withdrawal.")
                            else:
                                conn.commit(); add_request_message(conn,int(item.id),"WITHDRAWAL",reason,username); notify_approval_team(conn,f"Request withdrawn · AP-{item.id}",reason,item.request_kind,item.id,username); st.success("Request withdrawn. No operational change was posted."); st.rerun()


def render_notifications(conn):
    page_header("Notification Centre", "Follow approval requests, decisions and actions requiring your attention.")
    inbox,my_requests=st.tabs(["Notifications","My Requests"])
    with inbox: _render_inbox(conn)
    with my_requests: _render_my_requests(conn)
