from datetime import datetime
import io

import pandas as pd
import streamlit as st

from audit import record_event
from ui import page_header


DEPOT_STATUSES = ["ACTIVE","MAINTENANCE","INACTIVE"]
TANK_STATUSES = ["AVAILABLE","RECEIVING","ISSUING","MAINTENANCE","QUARANTINED","INACTIVE"]


def ensure_storage_schema(conn):
    cursor=conn.cursor()
    try:
        cursor.execute("""CREATE TABLE IF NOT EXISTS depots (
            id SERIAL PRIMARY KEY,code TEXT UNIQUE NOT NULL,name TEXT NOT NULL,address TEXT,emirate TEXT,
            manager_name TEXT,phone TEXT,latitude REAL,longitude REAL,status TEXT NOT NULL DEFAULT 'ACTIVE',
            notes TEXT,created_by TEXT,created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS storage_tanks (
            id SERIAL PRIMARY KEY,depot_id INTEGER NOT NULL REFERENCES depots(id),code TEXT NOT NULL,name TEXT NOT NULL,
            product_id INTEGER NOT NULL REFERENCES products(id),capacity_liters REAL NOT NULL CHECK(capacity_liters>0),
            safe_capacity_liters REAL NOT NULL CHECK(safe_capacity_liters>0),minimum_stock_liters REAL NOT NULL DEFAULT 0,
            reorder_level_liters REAL NOT NULL DEFAULT 0,dead_stock_liters REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'AVAILABLE',notes TEXT,created_by TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,UNIQUE(depot_id,code))""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS tank_transactions (
            id BIGSERIAL PRIMARY KEY,tank_id INTEGER NOT NULL REFERENCES storage_tanks(id),
            movement_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,liters REAL NOT NULL CHECK(liters>0),
            type TEXT NOT NULL CHECK(type IN ('IN','OUT')),movement_category TEXT NOT NULL DEFAULT 'STANDARD',
            product_id INTEGER REFERENCES products(id),partner_tank_transaction_id BIGINT,truck_transaction_id INTEGER,
            reference TEXT,notes TEXT,created_by TEXT,record_status TEXT NOT NULL DEFAULT 'POSTED',
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tanks_depot ON storage_tanks(depot_id,status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tank_transactions_tank_time ON tank_transactions(tank_id,movement_at DESC)")
        conn.commit()
    except Exception: conn.rollback(); raise


def _depots(conn):
    return pd.read_sql_query("""SELECT d.*,
        COUNT(DISTINCT t.id) AS tank_count,COALESCE(SUM(t.safe_capacity_liters),0) AS safe_capacity,
        COALESCE(SUM(x.balance),0) AS live_stock
        FROM depots d LEFT JOIN storage_tanks t ON t.depot_id=d.id
        LEFT JOIN (SELECT tank_id,SUM(CASE WHEN type='IN' THEN liters ELSE -liters END) AS balance
                   FROM tank_transactions GROUP BY tank_id) x ON x.tank_id=t.id
        GROUP BY d.id ORDER BY d.status,d.code""",conn)


def _tanks(conn):
    return pd.read_sql_query("""SELECT t.id,t.depot_id,d.code AS depot_code,d.name AS depot,
        t.code,t.name,p.name AS product,t.product_id,t.capacity_liters,t.safe_capacity_liters,
        t.minimum_stock_liters,t.reorder_level_liters,t.dead_stock_liters,t.status,t.notes,
        COALESCE(SUM(CASE WHEN tx.type='IN' THEN tx.liters ELSE -tx.liters END),0) AS balance,
        MAX(tx.movement_at) AS last_movement
        FROM storage_tanks t JOIN depots d ON d.id=t.depot_id JOIN products p ON p.id=t.product_id
        LEFT JOIN tank_transactions tx ON tx.tank_id=t.id GROUP BY t.id,d.code,d.name,p.name
        ORDER BY d.code,t.code""",conn)


@st.dialog("Edit depot")
def edit_depot(conn,item):
    with st.form(f"edit_depot_{item['id']}"):
        name=st.text_input("Depot name",str(item["name"])); address=st.text_area("Address",str(item["address"] or ""))
        a,b=st.columns(2); manager=a.text_input("Manager",str(item["manager_name"] or "")); phone=b.text_input("Phone",str(item["phone"] or ""))
        status=st.selectbox("Status",DEPOT_STATUSES,index=DEPOT_STATUSES.index(item["status"]) if item["status"] in DEPOT_STATUSES else 0)
        notes=st.text_area("Notes",str(item["notes"] or ""))
        if st.form_submit_button("Save depot",type="primary"):
            cursor=conn.cursor(); cursor.execute("""UPDATE depots SET name=%s,address=%s,manager_name=%s,phone=%s,status=%s,notes=%s WHERE id=%s""",
                (name,address or None,manager or None,phone or None,status,notes or None,int(item["id"]))); conn.commit()
            record_event(conn,"UPDATE","Storage","Depot",int(item["id"]),f"Updated depot {item['code']}"); st.rerun()


@st.dialog("Edit storage tank")
def edit_tank(conn,item):
    with st.form(f"edit_tank_{item['id']}"):
        st.markdown(f"#### {item['depot_code']} · {item['code']} · {item['product']}")
        a,b=st.columns(2); capacity=a.number_input("Maximum capacity (L)",min_value=1.0,value=float(item["capacity_liters"])); safe=b.number_input("Safe working capacity (L)",min_value=1.0,value=float(item["safe_capacity_liters"]))
        c,d,e=st.columns(3); minimum=c.number_input("Minimum stock",min_value=0.0,value=float(item["minimum_stock_liters"])); reorder=d.number_input("Reorder level",min_value=0.0,value=float(item["reorder_level_liters"])); dead=e.number_input("Dead stock",min_value=0.0,value=float(item["dead_stock_liters"]))
        status=st.selectbox("Tank status",TANK_STATUSES,index=TANK_STATUSES.index(item["status"]) if item["status"] in TANK_STATUSES else 0)
        notes=st.text_area("Notes",str(item["notes"] or ""))
        if st.form_submit_button("Save tank",type="primary"):
            balance=float(item["balance"] or 0)
            if safe>capacity: st.error("Safe capacity cannot exceed maximum capacity.")
            elif balance>safe: st.error(f"Safe capacity cannot be below current stock of {balance:,.2f} L.")
            elif minimum>reorder or reorder>safe: st.error("Use: minimum stock ≤ reorder level ≤ safe capacity.")
            elif dead>minimum: st.error("Dead stock should not exceed minimum stock.")
            else:
                cursor=conn.cursor(); cursor.execute("""UPDATE storage_tanks SET capacity_liters=%s,safe_capacity_liters=%s,
                    minimum_stock_liters=%s,reorder_level_liters=%s,dead_stock_liters=%s,status=%s,notes=%s WHERE id=%s""",
                    (capacity,safe,minimum,reorder,dead,status,notes or None,int(item["id"]))); conn.commit()
                record_event(conn,"UPDATE","Storage","Tank",int(item["id"]),f"Updated tank {item['depot_code']} {item['code']}"); st.rerun()


def render_storage(conn):
    ensure_storage_schema(conn)
    page_header("Depots & Storage","Manage depot locations, storage tanks, capacity and opening inventory.")
    depots=_depots(conn); tanks=_tanks(conn)
    total_stock=float(tanks["balance"].sum()) if not tanks.empty else 0; safe=float(tanks["safe_capacity_liters"].sum()) if not tanks.empty else 0
    low=tanks[(tanks["balance"]<=tanks["reorder_level_liters"]) & (tanks["status"]!="INACTIVE")] if not tanks.empty else tanks
    a,b,c,d=st.columns(4); a.metric("Live storage stock",f"{total_stock:,.0f} L"); b.metric("Safe capacity",f"{safe:,.0f} L"); c.metric("Active depots",len(depots[depots["status"]=="ACTIVE"]) if not depots.empty else 0); d.metric("Tanks to reorder",len(low))
    tab_live,tab_depot,tab_tank,tab_ledger=st.tabs(["Live storage","Add depot","Add tank","Storage ledger & export"])

    with tab_depot:
        with st.form("add_depot",clear_on_submit=True):
            a,b,c=st.columns(3); code=a.text_input("Depot code").strip().upper(); name=b.text_input("Depot name").strip(); emirate=c.selectbox("Emirate",["DXB","AUH","SHJ","AJM","RAK","FUJ","UAQ","OTHER"])
            address=st.text_area("Address"); d,e=st.columns(2); manager=d.text_input("Depot manager"); phone=e.text_input("Contact number"); notes=st.text_area("Notes")
            submit=st.form_submit_button("Create depot",type="primary")
        if submit:
            if not code or not name: st.error("Depot code and name are required.")
            else:
                try:
                    cursor=conn.cursor(); cursor.execute("""INSERT INTO depots(code,name,address,emirate,manager_name,phone,notes,created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(code,name,address or None,emirate,manager or None,phone or None,notes or None,st.session_state.get("user","System")))
                    depot_id=cursor.fetchone()[0]; conn.commit(); record_event(conn,"CREATE","Storage","Depot",depot_id,f"Created depot {code} · {name}"); st.success("Depot created."); st.rerun()
                except Exception as error: conn.rollback(); st.error(f"Depot could not be created: {error}")

    with tab_tank:
        if depots.empty: st.info("Create a depot first.")
        else:
            products=pd.read_sql_query("SELECT id,name FROM products WHERE active=TRUE ORDER BY name",conn); depot_map={f"{r.code} · {r.name}":int(r.id) for r in depots.itertuples()}; product_map=dict(zip(products["name"],products["id"]))
            with st.form("add_tank",clear_on_submit=True):
                a,b,c=st.columns(3); depot_label=a.selectbox("Depot",list(depot_map)); code=b.text_input("Tank code").strip().upper(); name=c.text_input("Tank name").strip()
                product=st.selectbox("Fuel product",list(product_map)); d,e,f=st.columns(3); capacity=d.number_input("Maximum capacity (L)",min_value=0.0,step=1000.0); safe_capacity=e.number_input("Safe working capacity (L)",min_value=0.0,step=1000.0); opening=f.number_input("Opening stock (L)",min_value=0.0,step=100.0)
                g,h,i=st.columns(3); minimum=g.number_input("Minimum stock (L)",min_value=0.0,step=100.0); reorder=h.number_input("Reorder level (L)",min_value=0.0,step=100.0); dead=i.number_input("Dead stock (L)",min_value=0.0,step=100.0)
                reference=st.text_input("Opening stock reference"); notes=st.text_area("Notes"); submit_tank=st.form_submit_button("Create tank",type="primary")
            if submit_tank:
                if not code or not name: st.error("Tank code and name are required.")
                elif capacity<=0 or safe_capacity<=0: st.error("Enter maximum and safe working capacities.")
                elif safe_capacity>capacity: st.error("Safe capacity cannot exceed maximum capacity.")
                elif opening>safe_capacity: st.error("Opening stock cannot exceed safe working capacity.")
                elif minimum>reorder or reorder>safe_capacity or dead>minimum: st.error("Use: dead stock ≤ minimum stock ≤ reorder level ≤ safe capacity.")
                else:
                    try:
                        cursor=conn.cursor(); cursor.execute("""INSERT INTO storage_tanks
                            (depot_id,code,name,product_id,capacity_liters,safe_capacity_liters,minimum_stock_liters,
                             reorder_level_liters,dead_stock_liters,status,notes,created_by)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'AVAILABLE',%s,%s) RETURNING id""",
                            (depot_map[depot_label],code,name,product_map[product],capacity,safe_capacity,minimum,reorder,dead,notes or None,st.session_state.get("user","System")))
                        tank_id=cursor.fetchone()[0]
                        if opening>0: cursor.execute("""INSERT INTO tank_transactions(tank_id,movement_at,liters,type,movement_category,product_id,reference,created_by)
                            VALUES (%s,CURRENT_TIMESTAMP,%s,'IN','OPENING',%s,%s,%s)""",(tank_id,opening,product_map[product],reference or None,st.session_state.get("user","System")))
                        conn.commit(); record_event(conn,"CREATE","Storage","Tank",tank_id,f"Created {depot_label} tank {code} with {opening:,.2f} L opening stock"); st.success("Tank created."); st.rerun()
                    except Exception as error: conn.rollback(); st.error(f"Tank could not be created: {error}")

    with tab_live:
        if depots.empty: st.info("No depots configured.")
        else:
            for _,depot in depots.iterrows():
                with st.expander(f"{depot['code']} · {depot['name']} · {depot['live_stock']:,.0f} L",expanded=True):
                    top,action=st.columns([4,1]); top.caption(f"{depot['emirate'] or ''} · {depot['status'].title()} · {int(depot['tank_count'])} tank(s)")
                    if action.button("Edit depot",key=f"edit_depot_{depot['id']}",use_container_width=True): edit_depot(conn,depot)
                    depot_tanks=tanks[tanks["depot_id"]==depot["id"]]
                    if depot_tanks.empty: st.caption("No tanks in this depot.")
                    for _,tank in depot_tanks.iterrows():
                        balance=float(tank["balance"]); safe_capacity=float(tank["safe_capacity_liters"]); fill=balance/safe_capacity if safe_capacity else 0
                        status="Critical" if balance<=tank["minimum_stock_liters"] else ("Reorder" if balance<=tank["reorder_level_liters"] else "Healthy")
                        with st.container(border=True):
                            x1,x2,x3,x4=st.columns([2,1.2,1.2,1]); x1.markdown(f"### {tank['code']} · {tank['name']}"); x1.caption(f"{tank['product']} · {tank['status'].title()}"); x2.metric("Stock",f"{balance:,.2f} L"); x3.metric("Fill",f"{fill*100:,.1f}%",status)
                            st.progress(max(0.0,min(fill,1.0)),text=f"Safe capacity {safe_capacity:,.0f} L · Available {max(safe_capacity-balance,0):,.0f} L")
                            if x4.button("Edit tank",key=f"edit_tank_{tank['id']}",use_container_width=True): edit_tank(conn,tank)

    with tab_ledger:
        ledger=pd.read_sql_query("""SELECT tx.id,tx.movement_at,d.code AS depot,t.code AS tank,p.name AS product,
            tx.type,tx.liters,tx.movement_category,tx.reference,tx.created_by,tx.record_status
            FROM tank_transactions tx JOIN storage_tanks t ON t.id=tx.tank_id JOIN depots d ON d.id=t.depot_id
            LEFT JOIN products p ON p.id=tx.product_id ORDER BY tx.id DESC""",conn)
        if ledger.empty: st.info("No storage movements recorded.")
        else:
            st.dataframe(ledger,use_container_width=True,hide_index=True,height=430)
            export=ledger.copy(); converted=pd.to_datetime(export["movement_at"],errors="coerce",utc=True); export["movement_at"]=converted.dt.tz_convert("Asia/Dubai").dt.tz_localize(None)
            buffer=io.BytesIO()
            with pd.ExcelWriter(buffer,engine="openpyxl") as writer: export.to_excel(writer,index=False,sheet_name="Storage Ledger")
            st.download_button("Download storage ledger",buffer.getvalue(),f"storage_ledger_{datetime.now():%Y%m%d_%H%M%S}.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
