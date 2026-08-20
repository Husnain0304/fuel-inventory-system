from datetime import datetime
import json

import pandas as pd
import streamlit as st

from audit import record_event
from rbac import can
from ui import page_header
from user_notifications import (add_request_message, notify_approval_team, notify_user,
                           request_messages, set_request_confirmation)


DEFAULT_LIMITS = {
    "SUPPLIER_RECEIPT_QUANTITY": (25000.0, "L", "Supplier receipt quantity requiring approval"),
    "SUPPLIER_RECEIPT_VALUE": (100000.0, "AED", "Supplier receipt value requiring approval"),
    "STOCK_ADJUSTMENT_QUANTITY": (500.0, "L", "Physical-count variance requiring approval"),
    "BOOKING_VALUE": (250000.0, "AED", "Supplier booking value requiring approval"),
}

DEFAULT_SLA_RULES = {
    "SUPPLIER_RECEIPT": (4, 1, "HIGH"),
    "SUPPLIER_BOOKING": (24, 4, "MEDIUM"),
    "CLAIM_RESOLUTION": (24, 4, "MEDIUM"),
    "BOOKING_CANCELLATION": (8, 2, "HIGH"),
    "RELEASE_CANCELLATION": (8, 2, "HIGH"),
    "COST_POLICY_CHANGE": (24, 4, "HIGH"),
}


def ensure_approval_schema(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("""CREATE TABLE IF NOT EXISTS approval_limits(
            rule_key TEXT PRIMARY KEY, rule_name TEXT NOT NULL, threshold REAL NOT NULL DEFAULT 0,
            unit TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE,
            updated_by TEXT, updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS approval_decisions(
            id BIGSERIAL PRIMARY KEY, source_module TEXT NOT NULL, source_type TEXT NOT NULL,
            source_id BIGINT NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED','OVERRIDE')),
            requested_by TEXT, decided_by TEXT NOT NULL, comment TEXT NOT NULL,
            decided_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_module,source_type,source_id,decision))""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS approval_requests(
            id BIGSERIAL PRIMARY KEY, request_kind TEXT NOT NULL,
            title TEXT NOT NULL, quantity REAL, monetary_value REAL,
            payload JSONB NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK(status IN ('PENDING','APPROVED','REJECTED','POSTED','FAILED','CANCELLED')),
            requested_by TEXT NOT NULL, requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_by TEXT, reviewed_at TIMESTAMPTZ, review_comment TEXT,
            posted_reference TEXT, failure_message TEXT)""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests(status,requested_at)")
        cursor.execute("""CREATE TABLE IF NOT EXISTS approval_sla_rules(
            request_kind TEXT PRIMARY KEY,target_hours INTEGER NOT NULL CHECK(target_hours>0),
            warning_hours INTEGER NOT NULL DEFAULT 1 CHECK(warning_hours>=0),
            priority TEXT NOT NULL DEFAULT 'MEDIUM' CHECK(priority IN ('LOW','MEDIUM','HIGH','CRITICAL')),
            enabled BOOLEAN NOT NULL DEFAULT TRUE,updated_by TEXT,updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""")
        for statement in (
            "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS priority TEXT DEFAULT 'MEDIUM'",
            "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ",
            "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMPTZ",
        ):
            cursor.execute(statement)
        for key, (threshold, unit, name) in DEFAULT_LIMITS.items():
            cursor.execute("""INSERT INTO approval_limits(rule_key,rule_name,threshold,unit)
                VALUES (%s,%s,%s,%s) ON CONFLICT(rule_key) DO NOTHING""", (key, name, threshold, unit))
        for kind,(target,warning,priority) in DEFAULT_SLA_RULES.items():
            cursor.execute("""INSERT INTO approval_sla_rules(request_kind,target_hours,warning_hours,priority)
                VALUES (%s,%s,%s,%s) ON CONFLICT(request_kind) DO NOTHING""",(kind,target,warning,priority))
        cursor.execute("""UPDATE approval_requests r SET
            priority=COALESCE(s.priority,'MEDIUM'),
            due_at=r.requested_at+(COALESCE(s.target_hours,24)*INTERVAL '1 hour')
            FROM approval_sla_rules s WHERE r.request_kind=s.request_kind AND r.due_at IS NULL""")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def approval_limit(conn, rule_key):
    ensure_approval_schema(conn)
    cursor = conn.cursor()
    cursor.execute("SELECT threshold,enabled FROM approval_limits WHERE rule_key=%s", (rule_key,))
    row = cursor.fetchone()
    return float(row[0]) if row and row[1] else None


def needs_approval(conn, rule_key, amount):
    threshold = approval_limit(conn, rule_key)
    return threshold is not None and threshold > 0 and float(amount or 0) >= threshold


def submit_approval_request(conn, request_kind, title, payload, requested_by, quantity=None, monetary_value=None):
    ensure_approval_schema(conn)
    cursor = conn.cursor()
    cursor.execute("SELECT target_hours,priority FROM approval_sla_rules WHERE request_kind=%s AND enabled=TRUE",(request_kind,))
    rule=cursor.fetchone(); target_hours=int(rule[0]) if rule else 24; priority=rule[1] if rule else "MEDIUM"
    cursor.execute("""INSERT INTO approval_requests
        (request_kind,title,quantity,monetary_value,payload,requested_by,priority,due_at)
        VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,CURRENT_TIMESTAMP+(%s*INTERVAL '1 hour')) RETURNING id""",
        (request_kind,title,quantity,monetary_value,json.dumps(payload,default=str),requested_by,priority,target_hours))
    request_id=cursor.fetchone()[0]; conn.commit()
    record_event(conn,"SUBMIT_FOR_APPROVAL","Approval Centre","Approval Request",request_id,title)
    notify_approval_team(conn,f"Approval required · AP-{request_id}",
                         f"{title}. Requested by {requested_by}.",request_kind,request_id,requested_by)
    set_request_confirmation(request_id,title)
    return request_id


def _record_decision(conn, module, source_type, source_id, decision, requester, reviewer, comment):
    cursor = conn.cursor()
    cursor.execute("""INSERT INTO approval_decisions
        (source_module,source_type,source_id,decision,requested_by,decided_by,comment)
        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (module, source_type, source_id, decision, requester, reviewer, comment))
    conn.commit()
    record_event(conn, decision, "Approval Centre", source_type, source_id,
                 f"{decision.title()} by {reviewer}. {comment}")
    notify_user(conn,requester,f"Request {decision.lower()} · {source_type} {source_id}",
                f"Your request was {decision.lower()} by {reviewer}. Comment: {comment}",
                decision,source_type,source_id,"Approvals",reviewer)


def _review_allowed(requester):
    reviewer = st.session_state.get("user", "")
    if not can(st.session_state.get("role", "VIEWER"), "APPROVE"):
        st.error("Your role does not allow approvals.")
        return False
    if requester and requester.strip().lower() == reviewer.strip().lower():
        st.error("You cannot approve or reject your own request. A different approver must review it.")
        return False
    return True


def _pending_counts(conn):
    queries = [
        "SELECT COUNT(*) FROM refill_requests WHERE status='PENDING'",
        "SELECT COUNT(*) FROM stock_reconciliations WHERE status='PENDING'",
        "SELECT COUNT(*) FROM transaction_change_requests WHERE status='PENDING'",
    ]
    cursor = conn.cursor(); values = []
    for query in queries:
        try:
            cursor.execute(query); values.append(int(cursor.fetchone()[0]))
        except Exception:
            conn.rollback(); values.append(0); cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM approval_requests WHERE status='PENDING'")
        values.append(int(cursor.fetchone()[0]))
    except Exception:
        conn.rollback(); values.append(0)
    return values


def _sla_label(due_at,warning_hours=1):
    if pd.isna(due_at): return "No deadline", "NORMAL"
    remaining=pd.to_datetime(due_at,utc=True)-pd.Timestamp.now(tz="UTC")
    seconds=remaining.total_seconds()
    if seconds<0: return f"Overdue by {abs(seconds)/3600:.1f} hours", "OVERDUE"
    if seconds<=float(warning_hours or 0)*3600: return f"Due in {seconds/3600:.1f} hours", "DUE_SOON"
    return f"Due in {seconds/3600:.1f} hours", "ON_TIME"


def process_approval_escalations(conn):
    overdue=pd.read_sql_query("""SELECT r.id,r.title,r.request_kind,r.requested_by,r.due_at
        FROM approval_requests r JOIN approval_sla_rules s ON s.request_kind=r.request_kind
        WHERE r.status='PENDING' AND s.enabled=TRUE AND r.due_at<CURRENT_TIMESTAMP AND r.escalated_at IS NULL""",conn)
    for item in overdue.itertuples():
        notify_approval_team(conn,f"Overdue approval escalated · AP-{item.id}",
            f"{item.title} is overdue and requires immediate review. Requested by {item.requested_by}.",
            item.request_kind,item.id,"System Escalation")
        cursor=conn.cursor(); cursor.execute("UPDATE approval_requests SET escalated_at=CURRENT_TIMESTAMP WHERE id=%s AND escalated_at IS NULL",(item.id,)); conn.commit()


def _execute_operational_request(conn, request_id, reviewer, comment):
    cursor=conn.cursor()
    cursor.execute("SELECT request_kind,payload,status,requested_by FROM approval_requests WHERE id=%s FOR UPDATE",(request_id,))
    row=cursor.fetchone()
    if not row or row[2] != "PENDING": raise ValueError("This request is no longer pending.")
    kind,payload,_,requester=row
    if isinstance(payload,str): payload=json.loads(payload)
    cursor.execute("""UPDATE approval_requests SET status='APPROVED',reviewed_by=%s,
        reviewed_at=CURRENT_TIMESTAMP,review_comment=%s,failure_message=NULL WHERE id=%s""",
        (reviewer,comment,request_id))
    conn.commit()
    try:
        if kind == "SUPPLIER_RECEIPT":
            from storage_operations import post_supplier_receipt
            movement_at=pd.to_datetime(payload["movement_at"]).to_pydatetime()
            transaction_id,_=post_supplier_receipt(
                conn,int(payload["tank_id"]),movement_at,float(payload["ordered"]),float(payload["dispatched"]),
                float(payload["accepted"]),int(payload["supplier_id"]),payload["method"],payload.get("vehicle"),
                payload.get("driver"),payload["reference"],payload.get("notes"),requester,payload.get("purchase_type","Credit purchase"),
                int(payload["booking_id"]) if payload.get("booking_id") else None,
                int(payload["release_id"]) if payload.get("release_id") else None,float(payload.get("unit_price") or 0))
            reference=f"STX-{transaction_id}"
        elif kind == "SUPPLIER_BOOKING":
            cursor=conn.cursor()
            cursor.execute("""INSERT INTO procurement_bookings
                (booking_number,supplier_id,product_id,booking_date,valid_from,valid_to,booked_liters,unit_price,
                 payment_terms,transport_responsibility,status,notes,created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'OPEN',%s,%s) RETURNING id""",
                (payload["booking_number"],int(payload["supplier_id"]),int(payload["product_id"]),payload["booking_date"],
                 payload["booking_date"],payload["valid_to"],float(payload["liters"]),float(payload["unit_price"]),
                 payload["payment_terms"],payload["transport"],payload.get("notes"),requester))
            booking_id=cursor.fetchone()[0]; conn.commit(); reference=f"BK-{booking_id}"
        elif kind == "CLAIM_RESOLUTION":
            cursor=conn.cursor(); claim_id=int(payload["claim_id"]); target=payload["target_status"]
            cursor.execute("SELECT status FROM supplier_claims WHERE id=%s FOR UPDATE",(claim_id,)); current=cursor.fetchone()
            if not current or current[0] in ("CLOSED","REJECTED"): raise ValueError("This claim is already resolved or no longer exists.")
            cursor.execute("""UPDATE supplier_claims SET status=%s,credit_note_number=%s,credit_note_date=%s,
                notes=COALESCE(%s,notes),resolved_by=%s,resolved_at=CURRENT_TIMESTAMP WHERE id=%s""",
                (target,payload.get("credit_note_number"),payload.get("credit_note_date"),payload.get("notes"),reviewer,claim_id))
            conn.commit(); reference=f"CL-{claim_id}"
        elif kind == "BOOKING_CANCELLATION":
            cursor=conn.cursor(); booking_id=int(payload["booking_id"])
            cursor.execute("SELECT status FROM procurement_bookings WHERE id=%s FOR UPDATE",(booking_id,)); current=cursor.fetchone()
            if not current or current[0] not in ("OPEN","PARTIALLY_USED"): raise ValueError("This booking can no longer be cancelled.")
            cursor.execute("""UPDATE procurement_bookings SET status='CANCELLED',closed_by=%s,
                closed_at=CURRENT_TIMESTAMP,notes=CONCAT(COALESCE(notes,''),%s) WHERE id=%s""",
                (reviewer,f"\nCancellation approved: {payload['reason']} · Ref: {payload['reference']}",booking_id))
            cursor.execute("UPDATE procurement_releases SET status='CANCELLED' WHERE booking_id=%s AND status IN ('OPEN','PARTIALLY_RECEIVED')",(booking_id,))
            conn.commit(); reference=f"BK-{booking_id}"
        elif kind == "RELEASE_CANCELLATION":
            cursor=conn.cursor(); release_id=int(payload["release_id"])
            cursor.execute("SELECT status FROM procurement_releases WHERE id=%s FOR UPDATE",(release_id,)); current=cursor.fetchone()
            if not current or current[0] != "OPEN": raise ValueError("This release can no longer be cancelled.")
            cursor.execute("SELECT COALESCE(SUM(accepted_liters),0) FROM tank_transactions WHERE booking_release_id=%s",(release_id,))
            if float(cursor.fetchone()[0] or 0)>0.005: raise ValueError("A release with received fuel cannot be cancelled.")
            cursor.execute("""UPDATE procurement_releases SET status='CANCELLED',
                notes=CONCAT(COALESCE(notes,''),%s) WHERE id=%s""",
                (f"\nCancellation approved by {reviewer}: {payload['reason']} · Ref: {payload['reference']}",release_id))
            conn.commit(); reference=f"RL-{release_id}"
        elif kind == "COST_POLICY_CHANGE":
            cursor=conn.cursor(); product_id=int(payload["product_id"])
            cursor.execute("""UPDATE product_cost_policies SET status='SUPERSEDED'
                WHERE product_id=%s AND effective_from=%s AND status='ACTIVE'""",(product_id,payload["effective_from"]))
            cursor.execute("""INSERT INTO product_cost_policies(product_id,effective_from,default_unit_cost,reason,
                reference,status,approved_request_id,created_by) VALUES (%s,%s,%s,%s,%s,'ACTIVE',%s,%s) RETURNING id""",
                (product_id,payload["effective_from"],float(payload["unit_cost"]),payload["reason"],payload["reference"],request_id,requester))
            policy_id=cursor.fetchone()[0]; conn.commit(); reference=f"CP-{policy_id}"
        else: raise ValueError("Unsupported approval request type.")
        cursor=conn.cursor(); cursor.execute("""UPDATE approval_requests SET status='POSTED',reviewed_by=%s,
            reviewed_at=CURRENT_TIMESTAMP,review_comment=%s,posted_reference=%s WHERE id=%s""",(reviewer,comment,reference,request_id)); conn.commit()
        _record_decision(conn,"Operations",kind.replace("_"," ").title(),request_id,"APPROVED",requester,reviewer,comment)
        return reference
    except Exception as error:
        conn.rollback(); cursor=conn.cursor(); cursor.execute("""UPDATE approval_requests SET status='PENDING',
            reviewed_by=NULL,reviewed_at=NULL,review_comment=NULL,failure_message=%s WHERE id=%s""",(str(error),request_id)); conn.commit(); raise


def _render_operational_requests(conn):
    data=pd.read_sql_query("""SELECT r.id,r.request_kind,r.title,r.quantity,r.monetary_value,r.payload,r.requested_by,
        r.requested_at,r.priority,r.due_at,r.escalated_at,COALESCE(s.warning_hours,1) AS warning_hours
        FROM approval_requests r LEFT JOIN approval_sla_rules s ON s.request_kind=r.request_kind
        WHERE r.status='PENDING' ORDER BY CASE r.priority WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MEDIUM' THEN 3 ELSE 4 END,r.due_at,r.id""",conn)
    if data.empty: st.success("No supplier receipts or bookings are waiting."); return
    for item in data.itertuples():
        with st.container(border=True):
            st.markdown(f"### AP-{item.id} · {item.title}")
            sla_text,sla_state=_sla_label(item.due_at,item.warning_hours)
            if sla_state=="OVERDUE": st.error(f"OVERDUE · {sla_text} · Priority {item.priority}")
            elif sla_state=="DUE_SOON": st.warning(f"DUE SOON · {sla_text} · Priority {item.priority}")
            else: st.info(f"{sla_text} · Priority {item.priority}")
            a,b,c=st.columns(3)
            a.metric("Quantity",f"{item.quantity:,.2f} L" if pd.notna(item.quantity) else "—")
            b.metric("Value",f"{item.monetary_value:,.2f}" if pd.notna(item.monetary_value) else "—")
            c.metric("Type",str(item.request_kind).replace("_"," ").title())
            st.caption(f"Requested by {item.requested_by} · {pd.to_datetime(item.requested_at):%d %b %Y %H:%M}")
            details=item.payload if isinstance(item.payload,dict) else json.loads(item.payload)
            if item.request_kind in ("BOOKING_CANCELLATION","RELEASE_CANCELLATION"):
                st.write(f"**Reason:** {details.get('reason','—')}  |  **Supporting reference:** {details.get('reference','—')}")
            elif item.request_kind == "CLAIM_RESOLUTION":
                st.write(f"**Requested outcome:** {details.get('target_status','—')}  |  **Credit note:** {details.get('credit_note_number') or '—'}")
                st.write(f"**Resolution notes:** {details.get('notes','—')}")
            elif item.request_kind == "SUPPLIER_RECEIPT":
                st.write(f"**Delivery reference:** {details.get('reference','—')}  |  **Accepted:** {float(details.get('accepted') or 0):,.2f} L")
            messages=request_messages(conn,int(item.id))
            if not messages.empty:
                with st.expander(f"Requester follow-ups · {len(messages[messages['message_type']=='FOLLOW_UP'])}"):
                    for message in messages.itertuples():
                        st.write(f"**{str(message.message_type).replace('_',' ').title()} · {message.created_by} · {pd.to_datetime(message.created_at):%d %b %Y %H:%M}**")
                        st.caption(message.message)
                    response=st.text_area("Response to requester",key=f"approver_response_{item.id}")
                    if st.button("Send response",key=f"send_response_{item.id}"):
                        if len(response.strip())<3: st.error("Enter a response.")
                        else:
                            add_request_message(conn,int(item.id),"APPROVER_RESPONSE",response,st.session_state["user"])
                            notify_user(conn,item.requested_by,f"Approver responded · AP-{item.id}",response,"INFO",item.request_kind,item.id,"Notifications",st.session_state["user"])
                            st.success("Response sent."); st.rerun()
            comment=st.text_input("Decision comment",key=f"op_comment_{item.id}")
            approve,reject=st.columns(2)
            if approve.button("Approve and post",key=f"op_approve_{item.id}",type="primary",use_container_width=True):
                if not comment.strip(): st.error("Enter a decision comment.")
                elif _review_allowed(item.requested_by):
                    try: reference=_execute_operational_request(conn,int(item.id),st.session_state["user"],comment.strip()); st.success(f"Approved and posted as {reference}."); st.rerun()
                    except Exception as error: st.error(str(error))
            if reject.button("Reject",key=f"op_reject_{item.id}",use_container_width=True):
                if not comment.strip(): st.error("Enter a rejection reason.")
                elif _review_allowed(item.requested_by):
                    cursor=conn.cursor(); cursor.execute("""UPDATE approval_requests SET status='REJECTED',reviewed_by=%s,
                        reviewed_at=CURRENT_TIMESTAMP,review_comment=%s WHERE id=%s AND status='PENDING'""",(st.session_state["user"],comment.strip(),item.id)); conn.commit()
                    _record_decision(conn,"Operations",str(item.request_kind).replace("_"," ").title(),item.id,"REJECTED",item.requested_by,st.session_state["user"],comment.strip()); st.rerun()


def _render_refills(conn):
    data = pd.read_sql_query("""SELECT rr.id,rr.truck_id,
        CONCAT(t.emirate,' ',t.plate_code,' ',t.plate_number) AS truck,
        rr.requested_liters,rr.requested_by,rr.timestamp
        FROM refill_requests rr JOIN trucks t ON t.id=rr.truck_id
        WHERE rr.status='PENDING' ORDER BY rr.id""", conn)
    if data.empty:
        st.success("No refill requests are waiting.")
        return
    for item in data.itertuples():
        with st.container(border=True):
            st.markdown(f"### RF-{item.id} · {item.truck}")
            st.write(f"**{item.requested_liters:,.2f} L** requested by **{item.requested_by or 'Unknown'}**")
            comment = st.text_input("Decision comment", key=f"rf_comment_{item.id}")
            approve, reject = st.columns(2)
            if approve.button("Approve and post", key=f"rf_approve_{item.id}", type="primary", use_container_width=True):
                if not comment.strip(): st.error("Enter a decision comment.")
                elif _review_allowed(item.requested_by):
                    cursor=conn.cursor()
                    try:
                        cursor.execute("SELECT status FROM refill_requests WHERE id=%s FOR UPDATE",(item.id,))
                        if cursor.fetchone()[0] != "PENDING": raise ValueError("This request is no longer pending.")
                        cursor.execute("""INSERT INTO transactions(truck_id,date,liters,type,created_by,movement_category)
                            VALUES (%s,CURRENT_DATE,%s,'IN',%s,'REFILL_APPROVAL') RETURNING id""",
                            (item.truck_id,item.requested_liters,st.session_state["user"]))
                        transaction_id=cursor.fetchone()[0]
                        cursor.execute("UPDATE refill_requests SET status='APPROVED' WHERE id=%s",(item.id,)); conn.commit()
                        _record_decision(conn,"Refill","Refill Request",item.id,"APPROVED",item.requested_by,st.session_state["user"],comment.strip())
                        st.success(f"Approved and posted as TX-{transaction_id}."); st.rerun()
                    except Exception as error: conn.rollback(); st.error(str(error))
            if reject.button("Reject", key=f"rf_reject_{item.id}", use_container_width=True):
                if not comment.strip(): st.error("Enter a rejection reason.")
                elif _review_allowed(item.requested_by):
                    cursor=conn.cursor(); cursor.execute("UPDATE refill_requests SET status='REJECTED' WHERE id=%s AND status='PENDING'",(item.id,)); conn.commit()
                    _record_decision(conn,"Refill","Refill Request",item.id,"REJECTED",item.requested_by,st.session_state["user"],comment.strip()); st.rerun()


def _render_reconciliations(conn):
    data = pd.read_sql_query("""SELECT r.id,r.recorded_by,r.reading_at,r.system_quantity,r.physical_quantity,
        r.variance_quantity,r.reason,CONCAT(t.emirate,' ',t.plate_code,' ',t.plate_number) AS truck
        FROM stock_reconciliations r JOIN trucks t ON t.id=r.truck_id
        WHERE r.status='PENDING' ORDER BY r.id""", conn)
    if data.empty: st.success("No stock adjustments are waiting."); return
    from reconciliation import _post_adjustment
    for item in data.itertuples():
        with st.container(border=True):
            st.markdown(f"### RC-{item.id} · {item.truck}")
            st.write(f"System **{item.system_quantity:,.2f} L** → physical **{item.physical_quantity:,.2f} L** · variance **{item.variance_quantity:+,.2f} L**")
            st.caption(f"Requested by {item.recorded_by} · {item.reason}")
            comment=st.text_input("Decision comment",key=f"hub_rc_comment_{item.id}")
            approve,reject=st.columns(2)
            if approve.button("Approve and post adjustment",key=f"hub_rc_approve_{item.id}",type="primary",use_container_width=True):
                if not comment.strip(): st.error("Enter a decision comment.")
                elif _review_allowed(item.recorded_by):
                    try: _post_adjustment(conn,int(item.id),st.session_state["user"],comment.strip()); _record_decision(conn,"Inventory Control","Reconciliation",item.id,"APPROVED",item.recorded_by,st.session_state["user"],comment.strip()); st.rerun()
                    except Exception as error: st.error(str(error))
            if reject.button("Reject",key=f"hub_rc_reject_{item.id}",use_container_width=True):
                if not comment.strip(): st.error("Enter a rejection reason.")
                elif _review_allowed(item.recorded_by):
                    cursor=conn.cursor(); cursor.execute("""UPDATE stock_reconciliations SET status='REJECTED',reviewed_by=%s,
                        reviewed_at=CURRENT_TIMESTAMP,review_comment=%s WHERE id=%s AND status='PENDING'""",(st.session_state["user"],comment.strip(),item.id)); conn.commit()
                    _record_decision(conn,"Inventory Control","Reconciliation",item.id,"REJECTED",item.recorded_by,st.session_state["user"],comment.strip()); st.rerun()


def _render_changes(conn):
    data=pd.read_sql_query("""SELECT r.id,r.transaction_id,r.request_type,r.reason,r.proposed_liters,r.requested_by,
        CONCAT(t.emirate,' ',t.plate_code,' ',t.plate_number) AS truck,tx.type,tx.liters
        FROM transaction_change_requests r JOIN transactions tx ON tx.id=r.transaction_id JOIN trucks t ON t.id=tx.truck_id
        WHERE r.status='PENDING' ORDER BY r.id""",conn)
    if data.empty: st.success("No corrections or reversals are waiting."); return
    from transaction_control import _post_request
    for item in data.itertuples():
        with st.container(border=True):
            st.markdown(f"### CR-{item.id} · {item.request_type} · TX-{item.transaction_id}")
            st.write(f"{item.truck} · original **{item.type} {item.liters:,.2f} L**")
            st.caption(f"Requested by {item.requested_by} · {item.reason}")
            comment=st.text_input("Decision comment",key=f"hub_cr_comment_{item.id}")
            approve,reject=st.columns(2)
            if approve.button("Approve and post",key=f"hub_cr_approve_{item.id}",type="primary",use_container_width=True):
                if not comment.strip(): st.error("Enter a decision comment.")
                elif _review_allowed(item.requested_by):
                    try: _post_request(conn,int(item.id),st.session_state["user"],comment.strip()); _record_decision(conn,"Transaction Control","Change Request",item.id,"APPROVED",item.requested_by,st.session_state["user"],comment.strip()); st.rerun()
                    except Exception as error: st.error(str(error))
            if reject.button("Reject",key=f"hub_cr_reject_{item.id}",use_container_width=True):
                if not comment.strip(): st.error("Enter a rejection reason.")
                elif _review_allowed(item.requested_by):
                    cursor=conn.cursor(); cursor.execute("""UPDATE transaction_change_requests SET status='REJECTED',reviewed_by=%s,
                        reviewed_at=CURRENT_TIMESTAMP,review_comment=%s WHERE id=%s AND status='PENDING'""",(st.session_state["user"],comment.strip(),item.id)); conn.commit()
                    _record_decision(conn,"Transaction Control","Change Request",item.id,"REJECTED",item.requested_by,st.session_state["user"],comment.strip()); st.rerun()


def render_approval_centre(conn):
    ensure_approval_schema(conn)
    process_approval_escalations(conn)
    page_header("Approval Centre", "Review controlled inventory decisions from one queue with complete accountability.")
    refills,reconciliations,changes,operations=_pending_counts(conn)
    a,b,c,d=st.columns(4); a.metric("Waiting approval",refills+reconciliations+changes+operations); b.metric("Operational requests",operations); c.metric("Stock adjustments",reconciliations); d.metric("Other controls",refills+changes)
    queue,policies,sla_dashboard,history=st.tabs(["Approval queue","Approval limits","SLA & workload","Decision history"])
    with queue:
        if not can(st.session_state.get("role","VIEWER"),"APPROVE"):
            st.info("You can view the queue, but only an Approver, Inventory Manager or Administrator can make decisions.")
        with st.expander(f"Supplier receipts and bookings · {operations}",expanded=bool(operations)): _render_operational_requests(conn)
        with st.expander(f"Refill requests · {refills}",expanded=bool(refills)): _render_refills(conn)
        with st.expander(f"Stock adjustments · {reconciliations}",expanded=bool(reconciliations)): _render_reconciliations(conn)
        with st.expander(f"Corrections and reversals · {changes}",expanded=bool(changes)): _render_changes(conn)
    with policies:
        limits=pd.read_sql_query("SELECT rule_key,rule_name,threshold,unit,enabled,updated_by,updated_at FROM approval_limits ORDER BY rule_name",conn)
        st.caption("These limits are the single control register for staged approval enforcement. Corrections, reversals and stock adjustments already require approval.")
        if st.session_state.get("role") == "ADMIN":
            edited=st.data_editor(limits,column_config={"rule_key":None,"rule_name":"Control","threshold":st.column_config.NumberColumn("Approval threshold",min_value=0.0),"unit":"Unit","enabled":"Enabled","updated_by":None,"updated_at":None},disabled=["rule_name","unit"],hide_index=True,use_container_width=True,key="approval_limits_editor")
            if st.button("Save approval limits",type="primary"):
                cursor=conn.cursor()
                for row in edited.itertuples(): cursor.execute("UPDATE approval_limits SET threshold=%s,enabled=%s,updated_by=%s,updated_at=CURRENT_TIMESTAMP WHERE rule_key=%s",(float(row.threshold),bool(row.enabled),st.session_state["user"],row.rule_key))
                conn.commit(); record_event(conn,"UPDATE_LIMITS","Approval Centre","Approval Policy",None,"Updated approval thresholds"); st.success("Approval limits saved."); st.rerun()
        else: st.dataframe(limits.drop(columns=["rule_key"]),use_container_width=True,hide_index=True)
    with sla_dashboard:
        pending=pd.read_sql_query("""SELECT r.id,r.request_kind,r.title,r.priority,r.requested_by,r.requested_at,r.due_at,
            r.escalated_at,COALESCE(s.warning_hours,1) AS warning_hours
            FROM approval_requests r LEFT JOIN approval_sla_rules s ON s.request_kind=r.request_kind
            WHERE r.status='PENDING' ORDER BY r.due_at""",conn)
        completed=pd.read_sql_query("""SELECT request_kind,EXTRACT(EPOCH FROM (reviewed_at-requested_at))/3600.0 AS approval_hours
            FROM approval_requests WHERE status IN ('POSTED','REJECTED') AND reviewed_at IS NOT NULL""",conn)
        overdue_count=int((pd.to_datetime(pending["due_at"],utc=True)<pd.Timestamp.now(tz="UTC")).sum()) if not pending.empty else 0
        due_soon=0
        if not pending.empty:
            remaining=(pd.to_datetime(pending["due_at"],utc=True)-pd.Timestamp.now(tz="UTC")).dt.total_seconds()/3600
            due_soon=int(((remaining>=0)&(remaining<=pending["warning_hours"])).sum())
        a,b,c,d=st.columns(4); a.metric("Pending",len(pending)); b.metric("Due soon",due_soon); c.metric("Overdue",overdue_count); d.metric("Average approval time",f"{completed['approval_hours'].mean():.1f} h" if not completed.empty else "—")
        st.subheader("SLA rules")
        rules=pd.read_sql_query("SELECT request_kind,target_hours,warning_hours,priority,enabled,updated_by,updated_at FROM approval_sla_rules ORDER BY request_kind",conn)
        if st.session_state.get("role")=="ADMIN":
            edited=st.data_editor(rules,column_config={"request_kind":"Request type","target_hours":st.column_config.NumberColumn("Target hours",min_value=1,step=1),"warning_hours":st.column_config.NumberColumn("Due-soon warning (hours)",min_value=0,step=1),"priority":st.column_config.SelectboxColumn("Priority",options=["LOW","MEDIUM","HIGH","CRITICAL"]),"enabled":"Enabled","updated_by":None,"updated_at":None},disabled=["request_kind"],hide_index=True,use_container_width=True,key="sla_rules_editor")
            if st.button("Save SLA rules",type="primary"):
                cursor=conn.cursor()
                for row in edited.itertuples(): cursor.execute("""UPDATE approval_sla_rules SET target_hours=%s,warning_hours=%s,priority=%s,enabled=%s,updated_by=%s,updated_at=CURRENT_TIMESTAMP WHERE request_kind=%s""",(int(row.target_hours),int(row.warning_hours),row.priority,bool(row.enabled),st.session_state["user"],row.request_kind))
                conn.commit(); record_event(conn,"UPDATE_SLA","Approval Centre","SLA Rules",None,"Updated approval SLA rules"); st.success("SLA rules saved. New requests will use the updated deadlines."); st.rerun()
        else: st.dataframe(rules.drop(columns=["updated_by"]),use_container_width=True,hide_index=True)
        st.subheader("Current workload")
        if pending.empty: st.success("No AP requests are pending.")
        else:
            workload=pending.copy(); workload["SLA"]=workload.apply(lambda r:_sla_label(r["due_at"],r["warning_hours"])[0],axis=1)
            st.dataframe(workload[["id","request_kind","title","priority","requested_by","requested_at","due_at","SLA","escalated_at"]],use_container_width=True,hide_index=True,height=380)
        if not completed.empty:
            summary=completed.groupby("request_kind",as_index=False).agg(Completed=("approval_hours","count"),Average_Hours=("approval_hours","mean"),Maximum_Hours=("approval_hours","max"))
            st.subheader("Approval performance by request type"); st.dataframe(summary,use_container_width=True,hide_index=True)
    with history:
        decisions=pd.read_sql_query("SELECT id,decided_at,source_module,source_type,source_id,decision,requested_by,decided_by,comment FROM approval_decisions ORDER BY id DESC",conn)
        if decisions.empty: st.info("No central approval decisions have been recorded yet.")
        else: st.dataframe(decisions,use_container_width=True,hide_index=True,height=480)
