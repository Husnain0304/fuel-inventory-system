from datetime import date

import pandas as pd
import streamlit as st

from audit import record_event


def _inventory(conn):
    return pd.read_sql_query("""
        SELECT tr.id, tr.emirate, tr.plate_code, tr.plate_number,
               CONCAT(tr.emirate,' ',tr.plate_code,' ',tr.plate_number) AS truck,
               p.name AS product, tr.product_id, tr.capacity_liters,
               tr.minimum_stock_liters, tr.reorder_level_liters,
               tr.operational_status, tr.selling_price_per_liter, tr.notes,
               COALESCE(SUM(CASE WHEN tx.type='IN' THEN tx.liters ELSE -tx.liters END),0) AS balance,
               MAX(tx.date) AS last_movement
        FROM trucks tr
        LEFT JOIN products p ON p.id=tr.product_id
        LEFT JOIN transactions tx ON tx.truck_id=tr.id
        GROUP BY tr.id,p.name ORDER BY tr.operational_status,tr.emirate,tr.plate_code,tr.plate_number
    """, conn)


@st.dialog("Edit inventory profile")
def edit_truck(conn, truck):
    products = pd.read_sql_query("SELECT id,name FROM products WHERE active=TRUE ORDER BY name", conn)
    product_map = dict(zip(products["name"], products["id"]))
    current_product = truck["product"] if truck["product"] in product_map else list(product_map)[0]
    with st.form(f"edit_truck_{truck['id']}"):
        st.markdown(f"#### {truck['truck']}")
        c1, c2 = st.columns(2)
        product = c1.selectbox("Fuel product", list(product_map), index=list(product_map).index(current_product))
        status_options = ["ACTIVE", "MAINTENANCE", "QUARANTINED", "INACTIVE"]
        current_status = truck["operational_status"] if truck["operational_status"] in status_options else "ACTIVE"
        status = c2.selectbox("Operating status", status_options, index=status_options.index(current_status))
        capacity = c1.number_input("Tank capacity (L)", min_value=0.0, value=float(truck["capacity_liters"] or 0), step=500.0)
        minimum = c2.number_input("Minimum safe stock (L)", min_value=0.0, value=float(truck["minimum_stock_liters"] or 0), step=100.0)
        reorder = c1.number_input("Reorder level (L)", min_value=0.0, value=float(truck["reorder_level_liters"] or 0), step=100.0)
        price = c2.number_input("Custom selling price", min_value=0.0, value=float(truck["selling_price_per_liter"] or 0), format="%.3f")
        notes = st.text_area("Notes", value=str(truck["notes"] or ""))
        if st.form_submit_button("Save inventory profile", type="primary"):
            if capacity and float(truck["balance"]) > capacity:
                st.error(f"Capacity cannot be below the current stock of {truck['balance']:,.2f} L.")
            elif capacity and reorder > capacity:
                st.error("Reorder level cannot exceed capacity.")
            elif reorder and minimum > reorder:
                st.error("Minimum stock cannot exceed the reorder level.")
            else:
                cursor = conn.cursor()
                cursor.execute("""UPDATE trucks SET product_id=%s, operational_status=%s,
                    capacity_liters=%s, minimum_stock_liters=%s, reorder_level_liters=%s,
                    selling_price_per_liter=%s, notes=%s WHERE id=%s""",
                    (product_map[product], status, capacity or None, minimum or None,
                     reorder or None, price or None, notes or None, int(truck["id"])))
                conn.commit()
                record_event(conn, "UPDATE", "Fleet Inventory", "Truck", int(truck["id"]),
                             f"Updated inventory profile for {truck['truck']}", new_values={
                                 "product":product,"status":status,"capacity":capacity,
                                 "minimum_stock":minimum,"reorder_level":reorder})
                st.success("Inventory profile updated.")
                st.rerun()


def render_trucks(conn, cursor):
    products = pd.read_sql_query("SELECT id,name FROM products WHERE active=TRUE ORDER BY name", conn)
    product_map = dict(zip(products["name"], products["id"]))
    fleet = _inventory(conn)

    if not fleet.empty:
        active = fleet[fleet["operational_status"] == "ACTIVE"]
        total = float(active["balance"].sum())
        capacity = float(active["capacity_liters"].fillna(0).sum())
        low = fleet[(fleet["operational_status"] == "ACTIVE") &
                    (fleet["balance"] <= fleet["minimum_stock_liters"].fillna(-1))]
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Live truck inventory", f"{total:,.0f} L")
        c2.metric("Configured capacity", f"{capacity:,.0f} L")
        c3.metric("Active trucks", f"{len(active)}")
        c4.metric("Low-stock trucks", f"{len(low)}")

    tab_live, tab_add, tab_products = st.tabs(["Live fleet inventory", "Register truck", "Fuel products"])
    with tab_add:
        st.subheader("Register a fuel truck")
        st.caption("Create the vehicle and its opening inventory in one controlled step.")
        with st.form("register_inventory_truck", clear_on_submit=True):
            a,b,c = st.columns(3)
            emirate = a.selectbox("Emirate", ["DXB","AUH","SHJ","AJM","RAK","FUJ","UAQ"])
            plate_code = b.text_input("Plate code").strip().upper()
            plate_number = c.text_input("Plate number").strip().upper()
            d,e,f = st.columns(3)
            product = d.selectbox("Fuel product", list(product_map))
            capacity = e.number_input("Tank capacity (L)", min_value=0.0, step=500.0)
            opening = f.number_input("Opening stock (L)", min_value=0.0, step=100.0)
            g,h,i = st.columns(3)
            minimum = g.number_input("Minimum safe stock (L)", min_value=0.0, step=100.0)
            reorder = h.number_input("Reorder level (L)", min_value=0.0, step=100.0)
            opening_date = i.date_input("Opening stock date", value=date.today())
            price = st.number_input("Custom selling price (optional)", min_value=0.0, format="%.3f")
            submitted = st.form_submit_button("Register truck", type="primary")
        if submitted:
            if not plate_code or not plate_number:
                st.error("Plate code and plate number are required.")
            elif capacity <= 0:
                st.error("Enter the truck tank capacity.")
            elif opening > capacity:
                st.error("Opening stock cannot exceed tank capacity.")
            elif reorder > capacity or minimum > reorder:
                st.error("Use: minimum stock ≤ reorder level ≤ capacity.")
            else:
                try:
                    cursor.execute("""INSERT INTO trucks
                        (emirate,plate_code,plate_number,selling_price_per_liter,product_id,
                         capacity_liters,minimum_stock_liters,reorder_level_liters,operational_status)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'ACTIVE') RETURNING id""",
                        (emirate,plate_code,plate_number,price or None,product_map[product],
                         capacity,minimum,reorder))
                    truck_id = cursor.fetchone()[0]
                    if opening > 0:
                        cursor.execute("""INSERT INTO transactions
                            (truck_id,date,liters,type,product_id,movement_category,created_by)
                            VALUES (%s,%s,%s,'IN',%s,'OPENING',%s)""",
                            (truck_id,str(opening_date),opening,product_map[product],st.session_state.get("user","System")))
                    conn.commit()
                    record_event(conn,"CREATE","Fleet Inventory","Truck",truck_id,
                                 f"Registered {emirate} {plate_code} {plate_number} with {opening:,.2f} L opening stock")
                    st.success("Truck and opening inventory created.")
                    st.rerun()
                except Exception as error:
                    conn.rollback()
                    st.error(f"The truck could not be registered: {error}")

    with tab_products:
        st.subheader("Fuel products")
        with st.form("add_product", clear_on_submit=True):
            p1,p2 = st.columns(2)
            code = p1.text_input("Product code").strip().upper()
            name = p2.text_input("Product name").strip()
            if st.form_submit_button("Add product"):
                if code and name:
                    try:
                        cursor.execute("INSERT INTO products (code,name,unit) VALUES (%s,%s,'L')", (code,name))
                        conn.commit(); st.success("Product added."); st.rerun()
                    except Exception:
                        conn.rollback(); st.error("That product code or name already exists.")
        st.dataframe(products, use_container_width=True, hide_index=True,
                     column_config={"id":None,"name":"Available product"})

    with tab_live:
        if fleet.empty:
            st.info("No trucks have been registered.")
            return
        show_inactive = st.toggle("Show inactive trucks", value=False)
        view = fleet if show_inactive else fleet[fleet["operational_status"] != "INACTIVE"]
        for _, row in view.iterrows():
            capacity = float(row["capacity_liters"] or 0)
            balance = float(row["balance"] or 0)
            fill = balance / capacity if capacity else 0
            minimum = float(row["minimum_stock_liters"] or 0)
            status = "Critical" if minimum and balance <= minimum else ("Setup required" if not capacity else "Healthy")
            with st.container(border=True):
                title, stock, state, actions = st.columns([2.2,1.3,1.2,1])
                title.markdown(f"### {row['truck']}")
                title.caption(f"{row['product'] or 'No product'} · {row['operational_status'].title()}")
                stock.metric("Current stock", f"{balance:,.2f} L")
                state.metric("Fill level", f"{fill*100:,.1f}%", status)
                st.progress(max(0.0,min(fill,1.0)), text=f"Capacity {capacity:,.0f} L · Available space {max(capacity-balance,0):,.0f} L")
                if actions.button("Edit profile", key=f"edit_profile_{row['id']}", use_container_width=True):
                    edit_truck(conn,row)
