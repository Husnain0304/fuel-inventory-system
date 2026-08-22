from datetime import date
import io

import pandas as pd
import streamlit as st

from audit import record_event
from ui import page_header
from rbac import can


def ensure_transaction_control_schema(conn):
    """Idempotent local migration so hot Streamlit deploys cannot skip required columns."""
    cursor = conn.cursor()
    try:
        statements = (
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS record_status TEXT DEFAULT 'POSTED'",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS reversal_of_transaction_id INTEGER",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS reversed_by_transaction_id INTEGER",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS correction_of_transaction_id INTEGER",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS change_reason TEXT",
        )
        for statement in statements:
            cursor.execute(statement)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transaction_change_requests (
                id BIGSERIAL PRIMARY KEY,
                transaction_id INTEGER NOT NULL REFERENCES transactions(id),
                partner_transaction_id INTEGER REFERENCES transactions(id),
                request_type TEXT NOT NULL CHECK(request_type IN ('CORRECTION','REVERSAL')),
                reason TEXT NOT NULL,
                proposed_date TEXT,
                proposed_liters REAL,
                proposed_supplier_id INTEGER REFERENCES suppliers(id),
                status TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK(status IN ('PENDING','APPROVED','REJECTED','POSTED','CANCELLED')),
                requested_by TEXT NOT NULL,
                requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_by TEXT,
                reviewed_at TIMESTAMPTZ,
                review_comment TEXT,
                reversal_transaction_id INTEGER REFERENCES transactions(id),
                replacement_transaction_id INTEGER REFERENCES transactions(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_change_requests_status ON transaction_change_requests(status, requested_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_record_status ON transactions(record_status, id DESC)")
        cursor.execute("UPDATE transactions SET record_status='POSTED' WHERE record_status IS NULL")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _transactions(conn):
    return pd.read_sql_query("""
        SELECT tx.id,tx.date,tx.truck_id,CONCAT(t.emirate,' ',t.plate_code,' ',t.plate_number) AS truck,
               tx.liters,tx.type,tx.supplier_id,s.name AS supplier,tx.transfer_partner_id,
               tx.movement_category,COALESCE(tx.record_status,'POSTED') AS record_status,
               tx.created_by,tx.created_at
        FROM transactions tx JOIN trucks t ON t.id=tx.truck_id
        LEFT JOIN suppliers s ON s.id=tx.supplier_id
        ORDER BY tx.id DESC
    """, conn)


def _requests(conn):
    return pd.read_sql_query("""
        SELECT r.*,CONCAT(t.emirate,' ',t.plate_code,' ',t.plate_number) AS truck,
               tx.type AS original_type,tx.liters AS original_liters,tx.date AS original_date
        FROM transaction_change_requests r JOIN transactions tx ON tx.id=r.transaction_id
        JOIN trucks t ON t.id=tx.truck_id ORDER BY r.id DESC
    """, conn)


def _validate_trucks(cursor, truck_ids):
    for truck_id in set(truck_ids):
        cursor.execute("""SELECT t.capacity_liters,
            COALESCE(SUM(CASE WHEN tx.type='IN' THEN tx.liters ELSE -tx.liters END),0)
            FROM trucks t LEFT JOIN transactions tx ON tx.truck_id=t.id
            WHERE t.id=%s GROUP BY t.id""", (truck_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError("A referenced truck no longer exists.")
        capacity,balance = float(row[0] or 0),float(row[1] or 0)
        if balance < -0.001:
            raise ValueError(f"Posting would create negative stock ({balance:,.2f} L).")
        if capacity and balance > capacity + 0.001:
            raise ValueError(f"Posting would exceed truck capacity ({balance:,.2f} L > {capacity:,.2f} L).")


def _insert_mirror(cursor, original, user, reason):
    original_id,truck_id,tx_date,liters,tx_type,supplier_id,product_id,partner_id = original
    mirror_type = "OUT" if tx_type == "IN" else "IN"
    cursor.execute("""INSERT INTO transactions
        (truck_id,date,liters,type,supplier_id,created_by,product_id,movement_category,
         record_status,reversal_of_transaction_id,change_reason)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'REVERSAL','POSTED',%s,%s) RETURNING id""",
        (truck_id,tx_date,liters,mirror_type,supplier_id,user,product_id,original_id,reason))
    return cursor.fetchone()[0]


def _post_request(conn, request_id, reviewer, comment):
    cursor = conn.cursor()
    try:
        cursor.execute("""SELECT transaction_id,partner_transaction_id,request_type,reason,
                                  proposed_date,proposed_liters,proposed_supplier_id,status
                           FROM transaction_change_requests WHERE id=%s FOR UPDATE""", (request_id,))
        request = cursor.fetchone()
        if not request or request[7] != "PENDING":
            raise ValueError("This request is no longer pending.")
        tx_id,partner_id,request_type,reason,new_date,new_liters,new_supplier_id,_ = request
        original_ids = [tx_id] + ([partner_id] if partner_id else [])
        cursor.execute("""SELECT id,truck_id,date,liters,type,supplier_id,product_id,transfer_partner_id
                           FROM transactions WHERE id=ANY(%s) ORDER BY id FOR UPDATE""", (original_ids,))
        originals = cursor.fetchall()
        if len(originals) != len(original_ids):
            raise ValueError("One of the original transaction records is missing.")
        if any((row[7] or None) not in (None, *(original_ids)) for row in originals):
            raise ValueError("The transfer links no longer match this request.")

        from period_close import assert_period_open
        for original in originals:
            assert_period_open(conn, original[2])
        if request_type == "CORRECTION":
            assert_period_open(conn, new_date or originals[0][2])

        reversal_ids = []
        for original in originals:
            reversal_ids.append(_insert_mirror(cursor,original,reviewer,reason))
        if len(reversal_ids) == 2:
            cursor.execute("UPDATE transactions SET transfer_partner_id=%s WHERE id=%s",(reversal_ids[1],reversal_ids[0]))
            cursor.execute("UPDATE transactions SET transfer_partner_id=%s WHERE id=%s",(reversal_ids[0],reversal_ids[1]))
        for original,reversal_id in zip(originals,reversal_ids):
            cursor.execute("UPDATE transactions SET record_status=%s,reversed_by_transaction_id=%s,change_reason=%s WHERE id=%s",
                           ("CORRECTED" if request_type=="CORRECTION" else "REVERSED",reversal_id,reason,original[0]))

        replacement_ids = []
        if request_type == "CORRECTION":
            if not new_liters or new_liters <= 0:
                raise ValueError("Corrected quantity must be greater than zero.")
            for original in originals:
                supplier = new_supplier_id if original[4] == "IN" and len(originals)==1 else original[5]
                cursor.execute("""INSERT INTO transactions
                    (truck_id,date,liters,type,supplier_id,created_by,product_id,movement_category,
                     record_status,correction_of_transaction_id,change_reason)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'POSTED',%s,%s) RETURNING id""",
                    (original[1],new_date or original[2],new_liters,original[4],supplier,reviewer,
                     original[6],original[4] == "IN" and "CORRECTION_IN" or "CORRECTION_OUT",original[0],reason))
                replacement_ids.append(cursor.fetchone()[0])
            if len(replacement_ids)==2:
                cursor.execute("UPDATE transactions SET transfer_partner_id=%s WHERE id=%s",(replacement_ids[1],replacement_ids[0]))
                cursor.execute("UPDATE transactions SET transfer_partner_id=%s WHERE id=%s",(replacement_ids[0],replacement_ids[1]))

        _validate_trucks(cursor,[row[1] for row in originals])
        cursor.execute("""UPDATE transaction_change_requests SET status='POSTED',reviewed_by=%s,
                           reviewed_at=CURRENT_TIMESTAMP,review_comment=%s,reversal_transaction_id=%s,
                           replacement_transaction_id=%s WHERE id=%s""",
                       (reviewer,comment,reversal_ids[0],replacement_ids[0] if replacement_ids else None,request_id))
        cursor.execute('INSERT INTO audit_log ("user",action,timestamp) VALUES (%s,%s,CURRENT_TIMESTAMP)',
                       (reviewer,f"POSTED {request_type} request CR-{request_id} for TX-{tx_id}"))
        conn.commit()
        record_event(conn,"POST_"+request_type,"Transaction Control","Change Request",request_id,
                     f"Posted {request_type.lower()} for TX-{tx_id}")
        return reversal_ids,replacement_ids
    except Exception:
        conn.rollback(); raise


def render_transaction_control(conn):
    ensure_transaction_control_schema(conn)
    page_header("Transaction Control","Correct or reverse inventory movements without deleting the original record.")
    transactions = _transactions(conn)
    requests = _requests(conn)
    pending = requests[requests["status"]=="PENDING"] if not requests.empty else requests
    a,b,c,d=st.columns(4)
    a.metric("Pending requests",len(pending)); b.metric("Total requests",len(requests))
    c.metric("Reversed records",len(transactions[transactions["record_status"]=="REVERSED"]) if not transactions.empty else 0)
    d.metric("Corrected records",len(transactions[transactions["record_status"]=="CORRECTED"]) if not transactions.empty else 0)
    tab_request,tab_review,tab_history=st.tabs(["Request correction/reversal","Review & post","Control history"])

    with tab_request:
        eligible=transactions[(transactions["record_status"]=="POSTED") &
                              (~transactions["movement_category"].isin(["REVERSAL","RECONCILIATION","OPENING"]))].copy()
        if eligible.empty: st.info("No posted transactions available.")
        else:
            options={f"TX-{int(row.id)} · {row.truck} · {row.type} {row.liters:,.2f} L · {row.date}":int(row.id)
                     for row in eligible.itertuples()}
            selected=st.selectbox("Original transaction",list(options))
            item=eligible[eligible["id"]==options[selected]].iloc[0]
            st.info(f"Original remains permanently visible: {item['type']} {item['liters']:,.2f} L for {item['truck']}.")
            with st.form("change_request_form"):
                request_type=st.radio("Required action",["CORRECTION","REVERSAL"],horizontal=True)
                reason=st.text_area("Reason (required)")
                if request_type=="CORRECTION":
                    x,y=st.columns(2)
                    proposed_date=x.date_input("Correct date",value=pd.to_datetime(item["date"]).date())
                    proposed_liters=y.number_input("Correct quantity (L)",min_value=0.01,value=float(item["liters"]))
                else: proposed_date,proposed_liters=None,None
                submit=st.form_submit_button("Submit change request",type="primary")
            if submit:
                if len(reason.strip())<5: st.error("Enter a clear reason of at least five characters.")
                else:
                    partner=int(item["transfer_partner_id"]) if pd.notna(item["transfer_partner_id"]) else None
                    cursor=conn.cursor()
                    cursor.execute("""SELECT COUNT(*) FROM transaction_change_requests
                                      WHERE transaction_id=ANY(%s) AND status='PENDING'""",([int(item["id"])] + ([partner] if partner else []),))
                    if cursor.fetchone()[0]: st.error("A pending request already exists for this transaction or transfer pair.")
                    else:
                        cursor.execute("""INSERT INTO transaction_change_requests
                            (transaction_id,partner_transaction_id,request_type,reason,proposed_date,
                             proposed_liters,proposed_supplier_id,requested_by)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                            (int(item["id"]),partner,request_type,reason.strip(),str(proposed_date) if proposed_date else None,
                             proposed_liters,int(item["supplier_id"]) if pd.notna(item["supplier_id"]) else None,
                             st.session_state.get("user","System")))
                        request_id=cursor.fetchone()[0]; conn.commit()
                        record_event(conn,"REQUEST_"+request_type,"Transaction Control","Change Request",request_id,
                                     f"Requested {request_type.lower()} for TX-{int(item['id'])}")
                        st.success(f"CR-{request_id} submitted. Inventory has not changed yet."); st.rerun()

    with tab_review:
        if not can(st.session_state.get("role","VIEWER"),"APPROVE"): st.info("Approver permission is required.")
        elif pending.empty: st.success("No requests are waiting for review.")
        else:
            for _,item in pending.iterrows():
                with st.container(border=True):
                    st.markdown(f"### CR-{item['id']} · {item['request_type']} · TX-{item['transaction_id']}")
                    st.write(f"**{item['truck']}** · Original {item['original_type']} {item['original_liters']:,.2f} L on {item['original_date']}")
                    st.write(f"**Reason:** {item['reason']}")
                    if item["request_type"]=="CORRECTION": st.write(f"**Proposed:** {item['proposed_liters']:,.2f} L on {item['proposed_date']}")
                    comment=st.text_input("Review comment",key=f"cr_comment_{item['id']}")
                    approve,reject=st.columns(2)
                    if approve.button("Approve and post",key=f"cr_approve_{item['id']}",type="primary",use_container_width=True):
                        if not comment.strip(): st.error("Enter a review comment.")
                        elif str(item["requested_by"]).strip().lower()==st.session_state.get("user","").strip().lower(): st.error("You cannot approve your own change request.")
                        else:
                            try: _post_request(conn,int(item["id"]),st.session_state["user"],comment.strip()); st.rerun()
                            except Exception as error: st.error(str(error))
                    if reject.button("Reject",key=f"cr_reject_{item['id']}",use_container_width=True):
                        if not comment.strip(): st.error("Enter a rejection reason.")
                        elif str(item["requested_by"]).strip().lower()==st.session_state.get("user","").strip().lower(): st.error("You cannot reject your own change request.")
                        else:
                            cursor=conn.cursor(); cursor.execute("""UPDATE transaction_change_requests SET status='REJECTED',
                                reviewed_by=%s,reviewed_at=CURRENT_TIMESTAMP,review_comment=%s WHERE id=%s AND status='PENDING'""",
                                (st.session_state["user"],comment.strip(),int(item["id"]))); conn.commit(); st.rerun()

    with tab_history:
        if requests.empty: st.info("No transaction-control requests yet.")
        else:
            st.dataframe(requests,use_container_width=True,hide_index=True,height=450)
            export=requests.copy()
            for col in ("requested_at","reviewed_at"):
                converted=pd.to_datetime(export[col],errors="coerce",utc=True)
                export[col]=converted.dt.tz_convert("Asia/Dubai").dt.tz_localize(None)
            buffer=io.BytesIO()
            with pd.ExcelWriter(buffer,engine="openpyxl") as writer: export.to_excel(writer,index=False,sheet_name="Transaction Control")
            st.download_button("Download control report",buffer.getvalue(),f"transaction_control_{date.today():%Y%m%d}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
