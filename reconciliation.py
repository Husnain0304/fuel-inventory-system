from datetime import datetime
import io

import pandas as pd
import streamlit as st

from audit import record_event
from ui import page_header


REASONS = [
    "Meter difference", "Physical measurement difference", "Temperature variation",
    "Spillage", "Leakage", "Data-entry correction", "Contaminated or rejected fuel",
    "Unexplained shortage", "Unexplained excess", "Other",
]


def _truck_data(conn):
    return pd.read_sql_query("""
        SELECT tr.id, CONCAT(tr.emirate,' ',tr.plate_code,' ',tr.plate_number) AS truck,
               tr.capacity_liters, tr.product_id, p.name AS product,
               COALESCE(SUM(CASE WHEN tx.type='IN' THEN tx.liters ELSE -tx.liters END),0) AS balance
        FROM trucks tr LEFT JOIN products p ON p.id=tr.product_id
        LEFT JOIN transactions tx ON tx.truck_id=tr.id
        WHERE tr.operational_status <> 'INACTIVE'
        GROUP BY tr.id,p.name ORDER BY truck
    """, conn)


def _history(conn):
    return pd.read_sql_query("""
        SELECT r.id, r.reading_at, CONCAT(t.emirate,' ',t.plate_code,' ',t.plate_number) AS truck,
               p.name AS product, r.system_quantity, r.physical_quantity,
               r.variance_quantity, r.variance_percent, r.reason, r.reference,
               r.status, r.recorded_by, r.recorded_at, r.reviewed_by,
               r.reviewed_at, r.review_comment, r.adjustment_transaction_id
        FROM stock_reconciliations r JOIN trucks t ON t.id=r.truck_id
        LEFT JOIN products p ON p.id=t.product_id ORDER BY r.id DESC
    """, conn)


def _post_adjustment(conn, reconciliation_id, reviewer, comment):
    cursor = conn.cursor()
    try:
        cursor.execute("""SELECT r.truck_id,r.variance_quantity,r.reading_at,r.status,
                                  t.product_id,t.capacity_liters
                           FROM stock_reconciliations r JOIN trucks t ON t.id=r.truck_id
                           WHERE r.id=%s FOR UPDATE""", (reconciliation_id,))
        row = cursor.fetchone()
        if not row or row[3] != "PENDING":
            raise ValueError("This reconciliation is no longer waiting for approval.")
        truck_id, variance, reading_at, _, product_id, capacity = row
        cursor.execute("""SELECT COALESCE(SUM(CASE WHEN type='IN' THEN liters ELSE -liters END),0)
                           FROM transactions WHERE truck_id=%s""", (truck_id,))
        current_balance = float(cursor.fetchone()[0] or 0)
        target_balance = current_balance + float(variance)
        if target_balance < -0.001:
            raise ValueError("The adjustment would create negative stock.")
        if capacity and target_balance > float(capacity) + 0.001:
            raise ValueError("The adjustment would exceed truck capacity.")
        transaction_id = None
        if abs(float(variance)) > 0.001:
            movement_type = "IN" if variance > 0 else "OUT"
            cursor.execute("""INSERT INTO transactions
                (truck_id,date,liters,type,created_by,product_id,movement_category)
                VALUES (%s,%s,%s,%s,%s,%s,'RECONCILIATION') RETURNING id""",
                (truck_id, str(pd.to_datetime(reading_at).date()), abs(float(variance)),
                 movement_type, reviewer, product_id))
            transaction_id = cursor.fetchone()[0]
        cursor.execute("""UPDATE stock_reconciliations SET status='POSTED', reviewed_by=%s,
                           reviewed_at=CURRENT_TIMESTAMP, review_comment=%s,
                           adjustment_transaction_id=%s, posted_at=CURRENT_TIMESTAMP WHERE id=%s""",
                       (reviewer, comment, transaction_id, reconciliation_id))
        cursor.execute('INSERT INTO audit_log ("user",action,timestamp) VALUES (%s,%s,CURRENT_TIMESTAMP)',
                       (reviewer, f"APPROVED reconciliation RC-{reconciliation_id}; adjustment TX-{transaction_id or 'NONE'}"))
        conn.commit()
        record_event(conn,"APPROVE_AND_POST","Inventory Control","Reconciliation",reconciliation_id,
                     f"Approved reconciliation and posted adjustment TX-{transaction_id or 'NONE'}")
        return transaction_id
    except Exception:
        conn.rollback()
        raise


def render_reconciliation(conn):
    page_header("Inventory Control", "Compare physical fuel with system stock and post controlled adjustments.")
    trucks = _truck_data(conn)
    history = _history(conn)
    pending_count = len(history[history["status"] == "PENDING"]) if not history.empty else 0
    variance_total = float(history["variance_quantity"].abs().sum()) if not history.empty else 0
    last_30 = history[pd.to_datetime(history["recorded_at"]) >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)] if not history.empty else history
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Pending approval", pending_count)
    c2.metric("Total counts", len(history))
    c3.metric("Absolute variance", f"{variance_total:,.2f} L")
    c4.metric("Counts in last 30 days", len(last_30))

    tab_count, tab_approve, tab_history = st.tabs(["Record physical count", "Review & approve", "History & export"])
    with tab_count:
        if trucks.empty:
            st.info("Configure a truck before recording a physical count.")
        else:
            truck_map = dict(zip(trucks["truck"], trucks["id"]))
            selected = st.selectbox("Truck", list(truck_map), key="recon_truck")
            truck = trucks[trucks["id"] == truck_map[selected]].iloc[0]
            capacity = float(truck["capacity_liters"] or 0)
            system = float(truck["balance"] or 0)
            a,b,c = st.columns(3)
            a.metric("System stock", f"{system:,.2f} L")
            b.metric("Tank capacity", f"{capacity:,.2f} L" if capacity else "Not configured")
            b.caption(f"Product: {truck['product'] or 'Not configured'}")
            with st.form("physical_count_form", clear_on_submit=True):
                rd, rt = st.columns(2)
                reading_date = rd.date_input("Reading date", value=datetime.now().date())
                reading_time = rt.time_input("Reading time", value=datetime.now().time().replace(microsecond=0))
                reading_at = datetime.combine(reading_date, reading_time)
                physical = st.number_input("Physical measured quantity (L)", min_value=0.0, step=10.0, format="%.2f")
                reason = st.selectbox("Reason for the count or variance", REASONS)
                reference = st.text_input("Meter, dip or document reference")
                notes = st.text_area("Notes")
                submit = st.form_submit_button("Submit for approval", type="primary")
            variance = physical - system
            c.metric("Expected variance", f"{variance:+,.2f} L")
            if submit:
                if not capacity:
                    st.error("Configure the truck capacity before recording a physical count.")
                elif physical > capacity:
                    st.error("Physical quantity cannot exceed truck capacity.")
                else:
                    percent = (variance / system * 100) if system else (100 if variance else 0)
                    cursor = conn.cursor()
                    cursor.execute("""INSERT INTO stock_reconciliations
                        (truck_id,reading_at,system_quantity,physical_quantity,variance_quantity,
                         variance_percent,reason,reference,notes,recorded_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                        (int(truck["id"]),reading_at,system,physical,variance,percent,reason,
                         reference or None,notes or None,st.session_state.get("user","System")))
                    reconciliation_id = cursor.fetchone()[0]
                    conn.commit()
                    record_event(conn,"CREATE","Inventory Control","Reconciliation",reconciliation_id,
                                 f"Submitted physical count for {selected}: {physical:,.2f} L; variance {variance:+,.2f} L")
                    st.success(f"RC-{reconciliation_id} submitted for approval. Inventory has not changed yet.")
                    st.rerun()

    with tab_approve:
        pending = history[history["status"] == "PENDING"] if not history.empty else history
        if st.session_state.get("role") != "ADMIN":
            st.info("Only an administrator can approve and post inventory adjustments.")
        elif pending.empty:
            st.success("No reconciliations are waiting for approval.")
        else:
            for _, item in pending.iterrows():
                with st.container(border=True):
                    h1,h2,h3,h4 = st.columns([2,1.2,1.2,1.2])
                    h1.markdown(f"### RC-{item['id']} · {item['truck']}")
                    h1.caption(f"Recorded by {item['recorded_by']} · {pd.to_datetime(item['reading_at']):%d %b %Y %H:%M}")
                    h2.metric("System", f"{item['system_quantity']:,.2f} L")
                    h3.metric("Physical", f"{item['physical_quantity']:,.2f} L")
                    h4.metric("Variance", f"{item['variance_quantity']:+,.2f} L", f"{item['variance_percent']:+,.2f}%")
                    st.write(f"**Reason:** {item['reason']}  |  **Reference:** {item['reference'] or '—'}")
                    comment = st.text_input("Review comment", key=f"review_comment_{item['id']}")
                    approve,reject = st.columns(2)
                    if approve.button("Approve and post adjustment", key=f"approve_{item['id']}", type="primary", use_container_width=True):
                        if not comment.strip():
                            st.error("Enter a review comment before approval.")
                        else:
                            try:
                                tx = _post_adjustment(conn,int(item["id"]),st.session_state["user"],comment.strip())
                                st.success(f"Approved and posted. Adjustment: TX-{tx}" if tx else "Approved. No adjustment was needed.")
                                st.rerun()
                            except Exception as error:
                                st.error(str(error))
                    if reject.button("Reject", key=f"reject_{item['id']}", use_container_width=True):
                        if not comment.strip():
                            st.error("Enter a rejection reason.")
                        else:
                            cursor = conn.cursor()
                            cursor.execute("""UPDATE stock_reconciliations SET status='REJECTED',reviewed_by=%s,
                                              reviewed_at=CURRENT_TIMESTAMP,review_comment=%s WHERE id=%s AND status='PENDING'""",
                                           (st.session_state["user"],comment.strip(),int(item["id"])))
                            conn.commit(); record_event(conn,"REJECT","Inventory Control","Reconciliation",int(item["id"]),comment.strip())
                            st.rerun()

    with tab_history:
        if history.empty:
            st.info("No physical counts recorded yet.")
        else:
            x1,x2 = st.columns(2)
            statuses = x1.multiselect("Status", sorted(history["status"].unique()), default=[])
            trucks_selected = x2.multiselect("Truck", sorted(history["truck"].unique()), default=[])
            view = history.copy()
            if statuses: view = view[view["status"].isin(statuses)]
            if trucks_selected: view = view[view["truck"].isin(trucks_selected)]
            st.dataframe(view, use_container_width=True, hide_index=True, height=430)
            export_view = view.copy()
            for column in ("reading_at", "recorded_at", "reviewed_at"):
                if column in export_view.columns:
                    converted = pd.to_datetime(export_view[column], errors="coerce", utc=True)
                    export_view[column] = converted.dt.tz_convert("Asia/Dubai").dt.tz_localize(None)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer,engine="openpyxl") as writer:
                export_view.to_excel(writer,index=False,sheet_name="Reconciliations")
            st.download_button("Download reconciliation report",buffer.getvalue(),
                               f"reconciliation_report_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
