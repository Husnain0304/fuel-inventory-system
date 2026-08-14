from datetime import datetime
import io

import pandas as pd
import streamlit as st

from audit import record_event
from ui import page_header


def ensure_operations_schema(conn):
    cursor=conn.cursor()
    try:
        for statement in (
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS tank_transaction_id BIGINT",
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS supplier_id INTEGER REFERENCES suppliers(id)",
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS transport_method TEXT",
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS vehicle_number TEXT",
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS driver_name TEXT",
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS ordered_liters REAL",
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS dispatched_liters REAL",
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS accepted_liters REAL",
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS variance_liters REAL",
        ): cursor.execute(statement)
        conn.commit()
    except Exception: conn.rollback(); raise


def _tanks(conn):
    return pd.read_sql_query("""SELECT t.id,t.depot_id,CONCAT(d.code,' · ',t.code,' · ',t.name) AS label,
        d.code AS depot,t.code,t.name,p.name AS product,t.product_id,t.safe_capacity_liters,t.status,
        COALESCE(SUM(CASE WHEN tx.type='IN' THEN tx.liters ELSE -tx.liters END),0) AS balance
        FROM storage_tanks t JOIN depots d ON d.id=t.depot_id JOIN products p ON p.id=t.product_id
        LEFT JOIN tank_transactions tx ON tx.tank_id=t.id GROUP BY t.id,d.code,p.name ORDER BY d.code,t.code""",conn)


def _trucks(conn):
    return pd.read_sql_query("""SELECT t.id,CONCAT(t.emirate,' ',t.plate_code,' ',t.plate_number) AS label,
        p.name AS product,t.product_id,t.capacity_liters,t.operational_status AS status,
        COALESCE(SUM(CASE WHEN tx.type='IN' THEN tx.liters ELSE -tx.liters END),0) AS balance
        FROM trucks t LEFT JOIN products p ON p.id=t.product_id LEFT JOIN transactions tx ON tx.truck_id=t.id
        GROUP BY t.id,p.name ORDER BY label""",conn)


def _tank_balance(cursor,tank_id):
    cursor.execute("SELECT COALESCE(SUM(CASE WHEN type='IN' THEN liters ELSE -liters END),0) FROM tank_transactions WHERE tank_id=%s",(tank_id,))
    return float(cursor.fetchone()[0] or 0)


def _truck_balance(cursor,truck_id):
    cursor.execute("SELECT COALESCE(SUM(CASE WHEN type='IN' THEN liters ELSE -liters END),0) FROM transactions WHERE truck_id=%s",(truck_id,))
    return float(cursor.fetchone()[0] or 0)


def post_supplier_receipt(conn,tank_id,movement_at,ordered,dispatched,accepted,supplier_id,method,vehicle,driver,reference,notes,user):
    cursor=conn.cursor()
    try:
        cursor.execute("SELECT product_id,safe_capacity_liters,status FROM storage_tanks WHERE id=%s FOR UPDATE",(tank_id,)); tank=cursor.fetchone()
        if not tank: raise ValueError("Tank no longer exists.")
        if tank[2] not in ("AVAILABLE","RECEIVING"): raise ValueError("Tank must be Available or Receiving.")
        balance=_tank_balance(cursor,tank_id)
        if accepted<=0: raise ValueError("Accepted quantity must be greater than zero.")
        if balance+accepted>float(tank[1])+0.001: raise ValueError(f"Safe capacity exceeded. Available: {max(float(tank[1])-balance,0):,.2f} L.")
        variance=accepted-dispatched
        cursor.execute("""INSERT INTO tank_transactions(tank_id,movement_at,liters,type,movement_category,product_id,
            supplier_id,transport_method,vehicle_number,driver_name,ordered_liters,dispatched_liters,accepted_liters,
            variance_liters,reference,notes,created_by) VALUES (%s,%s,%s,'IN','SUPPLIER_RECEIPT',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (tank_id,movement_at,accepted,tank[0],supplier_id,method,vehicle or None,driver or None,ordered,dispatched,accepted,variance,reference,notes or None,user))
        tx_id=cursor.fetchone()[0]; cursor.execute('INSERT INTO audit_log ("user",action,timestamp) VALUES (%s,%s,CURRENT_TIMESTAMP)',(user,f"RECEIVED {accepted:,.2f} L into tank; STX-{tx_id}")); conn.commit()
        record_event(conn,"SUPPLIER_RECEIPT","Storage Operations","Tank Transaction",tx_id,f"Accepted {accepted:,.2f} L; dispatch variance {variance:+,.2f} L")
        return tx_id,variance
    except Exception: conn.rollback(); raise


def post_tank_transfer(conn,source_id,destination_id,movement_at,liters,reference,notes,user):
    cursor=conn.cursor()
    try:
        cursor.execute("SELECT id,product_id,safe_capacity_liters,status FROM storage_tanks WHERE id=ANY(%s) ORDER BY id FOR UPDATE",(sorted([source_id,destination_id]),)); rows={r[0]:r for r in cursor.fetchall()}
        if len(rows)!=2: raise ValueError("One selected tank no longer exists.")
        source,destination=rows[source_id],rows[destination_id]
        if source[1]!=destination[1]: raise ValueError("Source and destination products must match.")
        if source[3] not in ("AVAILABLE","ISSUING") or destination[3] not in ("AVAILABLE","RECEIVING"): raise ValueError("Tank statuses do not permit this transfer.")
        source_balance=_tank_balance(cursor,source_id); destination_balance=_tank_balance(cursor,destination_id)
        if liters<=0 or liters>source_balance: raise ValueError(f"Insufficient source stock. Available: {source_balance:,.2f} L.")
        if destination_balance+liters>float(destination[2])+0.001: raise ValueError(f"Destination safe capacity exceeded. Available: {max(float(destination[2])-destination_balance,0):,.2f} L.")
        cursor.execute("""INSERT INTO tank_transactions(tank_id,movement_at,liters,type,movement_category,product_id,reference,notes,created_by)
            VALUES (%s,%s,%s,'OUT','TANK_TRANSFER',%s,%s,%s,%s) RETURNING id""",(source_id,movement_at,liters,source[1],reference,notes or None,user)); out_id=cursor.fetchone()[0]
        cursor.execute("""INSERT INTO tank_transactions(tank_id,movement_at,liters,type,movement_category,product_id,reference,notes,created_by)
            VALUES (%s,%s,%s,'IN','TANK_TRANSFER',%s,%s,%s,%s) RETURNING id""",(destination_id,movement_at,liters,destination[1],reference,notes or None,user)); in_id=cursor.fetchone()[0]
        cursor.execute("UPDATE tank_transactions SET partner_tank_transaction_id=%s WHERE id=%s",(in_id,out_id)); cursor.execute("UPDATE tank_transactions SET partner_tank_transaction_id=%s WHERE id=%s",(out_id,in_id)); conn.commit()
        record_event(conn,"TANK_TRANSFER","Storage Operations","Tank Transfer",out_id,f"Transferred {liters:,.2f} L; STX-{out_id} linked to STX-{in_id}"); return out_id,in_id
    except Exception: conn.rollback(); raise


def post_tank_truck(conn,tank_id,truck_id,movement_at,liters,direction,reference,notes,user):
    cursor=conn.cursor()
    try:
        cursor.execute("SELECT product_id,safe_capacity_liters,status FROM storage_tanks WHERE id=%s FOR UPDATE",(tank_id,)); tank=cursor.fetchone()
        cursor.execute("SELECT product_id,capacity_liters,operational_status FROM trucks WHERE id=%s FOR UPDATE",(truck_id,)); truck=cursor.fetchone()
        if not tank or not truck: raise ValueError("Tank or truck no longer exists.")
        if tank[0]!=truck[0]: raise ValueError("Tank and truck fuel products must match.")
        if truck[2]!="ACTIVE": raise ValueError("Truck must be Active.")
        tank_balance=_tank_balance(cursor,tank_id); truck_balance=_truck_balance(cursor,truck_id)
        if liters<=0: raise ValueError("Quantity must be greater than zero.")
        if direction=="TANK_TO_TRUCK":
            if tank[2] not in ("AVAILABLE","ISSUING"): raise ValueError("Tank is not available for issuing.")
            if liters>tank_balance: raise ValueError(f"Insufficient tank stock. Available: {tank_balance:,.2f} L.")
            if truck[1] and truck_balance+liters>float(truck[1])+0.001: raise ValueError(f"Truck capacity exceeded. Available: {max(float(truck[1])-truck_balance,0):,.2f} L.")
            tank_type,truck_type,category="OUT","IN","TANK_TO_TRUCK"
        else:
            if tank[2] not in ("AVAILABLE","RECEIVING"): raise ValueError("Tank is not available for receiving.")
            if liters>truck_balance: raise ValueError(f"Insufficient truck stock. Available: {truck_balance:,.2f} L.")
            if tank_balance+liters>float(tank[1])+0.001: raise ValueError(f"Tank safe capacity exceeded. Available: {max(float(tank[1])-tank_balance,0):,.2f} L.")
            tank_type,truck_type,category="IN","OUT","TRUCK_TO_TANK"
        cursor.execute("""INSERT INTO tank_transactions(tank_id,movement_at,liters,type,movement_category,product_id,reference,notes,created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(tank_id,movement_at,liters,tank_type,category,tank[0],reference,notes or None,user)); tank_tx=cursor.fetchone()[0]
        cursor.execute("""INSERT INTO transactions(truck_id,date,liters,type,created_by,product_id,movement_category,tank_transaction_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(truck_id,str(movement_at.date()),liters,truck_type,user,truck[0],category,tank_tx)); truck_tx=cursor.fetchone()[0]
        cursor.execute("UPDATE tank_transactions SET truck_transaction_id=%s WHERE id=%s",(truck_tx,tank_tx)); conn.commit()
        record_event(conn,category,"Storage Operations","Tank Transaction",tank_tx,f"Posted {liters:,.2f} L; STX-{tank_tx} linked to TX-{truck_tx}"); return tank_tx,truck_tx
    except Exception: conn.rollback(); raise


def render_storage_operations(conn):
    ensure_operations_schema(conn); page_header("Storage Operations","Receive and move fuel safely between suppliers, tanks and trucks.")
    tanks=_tanks(conn); trucks=_trucks(conn); user=st.session_state.get("user","System")
    if tanks.empty: st.warning("Create a depot and storage tank first."); return
    tab_receipt,tab_transfer,tab_loading,tab_return,tab_history=st.tabs(["Supplier receipt","Tank transfer","Load truck","Truck return","Movement history"])
    tank_map=dict(zip(tanks["label"],tanks["id"])); truck_map=dict(zip(trucks["label"],trucks["id"])) if not trucks.empty else {}
    with tab_receipt:
        suppliers=pd.read_sql_query("SELECT id,name FROM suppliers ORDER BY name",conn); supplier_map=dict(zip(suppliers["name"],suppliers["id"]))
        selected=st.selectbox("Receiving tank",list(tank_map),key="receipt_tank"); tank=tanks[tanks["id"]==tank_map[selected]].iloc[0]; st.info(f"Current {tank['balance']:,.2f} L · Available {max(tank['safe_capacity_liters']-tank['balance'],0):,.2f} L")
        with st.form("supplier_receipt"):
            a,b=st.columns(2); supplier=a.selectbox("Supplier",list(supplier_map)); method=b.selectbox("Transport method",["Supplier delivery","Company collection","Third-party transporter","Other"])
            c,d,e=st.columns(3); ordered=c.number_input("Ordered/released quantity",min_value=0.0); dispatched=d.number_input("Supplier dispatched quantity",min_value=0.0); accepted=e.number_input("Accepted into tank",min_value=0.0)
            f,g=st.columns(2); vehicle=f.text_input("Vehicle number"); driver=g.text_input("Driver name"); reference=st.text_input("Delivery note / ticket reference"); notes=st.text_area("Receipt notes"); submitted=st.form_submit_button("Post supplier receipt",type="primary")
        if submitted:
            if not reference.strip(): st.error("Delivery note or ticket reference is required.")
            else:
                try: tx,variance=post_supplier_receipt(conn,int(tank["id"]),datetime.now(),ordered,dispatched,accepted,supplier_map[supplier],method,vehicle,driver,reference.strip(),notes,user); st.success(f"STX-{tx} posted. Dispatch-to-accepted variance: {variance:+,.2f} L."); st.rerun()
                except Exception as error: st.error(str(error))
    with tab_transfer:
        source=st.selectbox("Source tank",list(tank_map),key="tank_source"); destinations=[x for x in tank_map if x!=source]; destination=st.selectbox("Destination tank",destinations,key="tank_destination") if destinations else None
        source_row=tanks[tanks["id"]==tank_map[source]].iloc[0]; st.info(f"Source stock: {source_row['balance']:,.2f} L")
        with st.form("tank_transfer"):
            liters=st.number_input("Transfer quantity",min_value=0.0); reference=st.text_input("Transfer reference"); notes=st.text_area("Transfer notes"); submit=st.form_submit_button("Post tank transfer",type="primary")
        if submit:
            if not destination: st.error("A destination tank is required.")
            elif not reference.strip(): st.error("Transfer reference is required.")
            else:
                try: out_id,in_id=post_tank_transfer(conn,tank_map[source],tank_map[destination],datetime.now(),liters,reference.strip(),notes,user); st.success(f"STX-{out_id} OUT linked to STX-{in_id} IN."); st.rerun()
                except Exception as error: st.error(str(error))
    with tab_loading:
        if not truck_map: st.info("No trucks available.")
        else:
            with st.form("tank_to_truck"):
                tank_label=st.selectbox("Source tank",list(tank_map)); truck_label=st.selectbox("Destination truck",list(truck_map)); liters=st.number_input("Loading quantity",min_value=0.0); reference=st.text_input("Loading ticket reference"); notes=st.text_area("Loading notes"); submit=st.form_submit_button("Load truck",type="primary")
            if submit:
                if not reference.strip(): st.error("Loading ticket reference is required.")
                else:
                    try: stx,tx=post_tank_truck(conn,tank_map[tank_label],truck_map[truck_label],datetime.now(),liters,"TANK_TO_TRUCK",reference.strip(),notes,user); st.success(f"STX-{stx} tank OUT linked to TX-{tx} truck IN."); st.rerun()
                    except Exception as error: st.error(str(error))
    with tab_return:
        if not truck_map: st.info("No trucks available.")
        else:
            with st.form("truck_to_tank"):
                truck_label=st.selectbox("Source truck",list(truck_map),key="return_truck"); tank_label=st.selectbox("Receiving tank",list(tank_map),key="return_tank"); liters=st.number_input("Return quantity",min_value=0.0); reference=st.text_input("Return reference"); notes=st.text_area("Return notes"); submit=st.form_submit_button("Post truck return",type="primary")
            if submit:
                if not reference.strip(): st.error("Return reference is required.")
                else:
                    try: stx,tx=post_tank_truck(conn,tank_map[tank_label],truck_map[truck_label],datetime.now(),liters,"TRUCK_TO_TANK",reference.strip(),notes,user); st.success(f"TX-{tx} truck OUT linked to STX-{stx} tank IN."); st.rerun()
                    except Exception as error: st.error(str(error))
    with tab_history:
        history=pd.read_sql_query("""SELECT tx.id,tx.movement_at,d.code AS depot,t.code AS tank,p.name AS product,tx.type,tx.liters,tx.movement_category,
            s.name AS supplier,tx.ordered_liters,tx.dispatched_liters,tx.accepted_liters,tx.variance_liters,tx.reference,tx.vehicle_number,tx.driver_name,
            tx.partner_tank_transaction_id,tx.truck_transaction_id,tx.created_by FROM tank_transactions tx JOIN storage_tanks t ON t.id=tx.tank_id
            JOIN depots d ON d.id=t.depot_id LEFT JOIN products p ON p.id=tx.product_id LEFT JOIN suppliers s ON s.id=tx.supplier_id ORDER BY tx.id DESC""",conn)
        st.dataframe(history,use_container_width=True,hide_index=True,height=480)
        if not history.empty:
            export=history.copy(); converted=pd.to_datetime(export["movement_at"],errors="coerce",utc=True); export["movement_at"]=converted.dt.tz_convert("Asia/Dubai").dt.tz_localize(None); buffer=io.BytesIO()
            with pd.ExcelWriter(buffer,engine="openpyxl") as writer: export.to_excel(writer,index=False,sheet_name="Storage Operations")
            st.download_button("Download operations report",buffer.getvalue(),f"storage_operations_{datetime.now():%Y%m%d_%H%M%S}.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
