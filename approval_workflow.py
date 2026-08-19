from datetime import datetime

import pandas as pd
import streamlit as st

from audit import record_event
from rbac import can
from ui import page_header


DEFAULT_LIMITS = {
    "SUPPLIER_RECEIPT_QUANTITY": (25000.0, "L", "Supplier receipt quantity requiring approval"),
    "SUPPLIER_RECEIPT_VALUE": (100000.0, "AED", "Supplier receipt value requiring approval"),
    "STOCK_ADJUSTMENT_QUANTITY": (500.0, "L", "Physical-count variance requiring approval"),
    "BOOKING_VALUE": (250000.0, "AED", "Supplier booking value requiring approval"),
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
        for key, (threshold, unit, name) in DEFAULT_LIMITS.items():
            cursor.execute("""INSERT INTO approval_limits(rule_key,rule_name,threshold,unit)
                VALUES (%s,%s,%s,%s) ON CONFLICT(rule_key) DO NOTHING""", (key, name, threshold, unit))
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


def _record_decision(conn, module, source_type, source_id, decision, requester, reviewer, comment):
    cursor = conn.cursor()
    cursor.execute("""INSERT INTO approval_decisions
        (source_module,source_type,source_id,decision,requested_by,decided_by,comment)
        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (module, source_type, source_id, decision, requester, reviewer, comment))
    conn.commit()
    record_event(conn, decision, "Approval Centre", source_type, source_id,
                 f"{decision.title()} by {reviewer}. {comment}")


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
    return values


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
    page_header("Approval Centre", "Review controlled inventory decisions from one queue with complete accountability.")
    refills,reconciliations,changes=_pending_counts(conn)
    a,b,c,d=st.columns(4); a.metric("Waiting approval",refills+reconciliations+changes); b.metric("Refills",refills); c.metric("Stock adjustments",reconciliations); d.metric("Corrections / reversals",changes)
    queue,policies,history=st.tabs(["Approval queue","Approval limits","Decision history"])
    with queue:
        if not can(st.session_state.get("role","VIEWER"),"APPROVE"):
            st.info("You can view the queue, but only an Approver, Inventory Manager or Administrator can make decisions.")
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
    with history:
        decisions=pd.read_sql_query("SELECT id,decided_at,source_module,source_type,source_id,decision,requested_by,decided_by,comment FROM approval_decisions ORDER BY id DESC",conn)
        if decisions.empty: st.info("No central approval decisions have been recorded yet.")
        else: st.dataframe(decisions,use_container_width=True,hide_index=True,height=480)
