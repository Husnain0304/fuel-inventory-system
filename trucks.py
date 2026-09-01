from datetime import date
from html import escape

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


@st.dialog("Truck inventory details", width="large")
def edit_truck(conn, truck):
    products = pd.read_sql_query("SELECT id,name FROM products WHERE active=TRUE ORDER BY name", conn)
    product_map = dict(zip(products["name"], products["id"]))
    if not product_map:
        st.error("Create an active fuel product before editing this truck.")
        if st.button("Close", use_container_width=True):
            st.rerun()
        return
    current_product = truck["product"] if truck["product"] in product_map else list(product_map)[0]
    balance = float(truck["balance"] or 0)
    capacity_now = float(truck["capacity_liters"] or 0)
    available_now = max(capacity_now - balance, 0)
    utilization_now = balance / capacity_now * 100 if capacity_now else 0
    minimum_now = float(truck["minimum_stock_liters"] or 0)
    reorder_now = float(truck["reorder_level_liters"] or 0)
    condition = "Critical" if minimum_now and balance <= minimum_now else ("Reorder" if reorder_now and balance <= reorder_now else ("Setup required" if not capacity_now else "Healthy"))

    st.markdown(
        f'<div style="background:linear-gradient(135deg,#101828,#1D2939);color:white;border-radius:16px;padding:18px 20px;margin-bottom:1rem">'
        f'<div style="font-size:.65rem;color:#98A2B3;font-weight:800;letter-spacing:.1em;text-transform:uppercase">Fleet inventory asset</div>'
        f'<div style="display:flex;justify-content:space-between;gap:1rem;align-items:center;margin-top:.3rem"><div style="font-size:1.45rem;font-weight:800">{escape(str(truck["truck"]))}</div>'
        f'<div style="background:#FFFFFF16;border:1px solid #FFFFFF22;border-radius:999px;padding:.38rem .65rem;font-size:.65rem;font-weight:800">{escape(condition.upper())}</div></div>'
        f'<div style="color:#D0D5DD;font-size:.76rem;margin-top:.25rem">{escape(str(current_product))} · {escape(str(truck["operational_status"]).title())}</div></div>',
        unsafe_allow_html=True,
    )
    summary = st.columns(4)
    summary[0].metric("Live inventory", f"{balance:,.2f} L")
    summary[1].metric("Capacity", f"{capacity_now:,.0f} L")
    summary[2].metric("Available", f"{available_now:,.0f} L")
    summary[3].metric("Utilization", f"{utilization_now:,.1f}%")
    st.progress(max(0.0, min(utilization_now / 100, 1.0)), text=f"Current tank utilization · {condition}")
    st.markdown("#### Inventory controls")
    st.caption("Update the truck profile below. Saving changes creates an audit record; it does not post an inventory movement.")
    with st.form(f"edit_truck_{truck['id']}"):
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
        if st.form_submit_button("Save changes", type="primary", use_container_width=True):
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
    close_column, ledger_column = st.columns(2)
    if close_column.button("Close", use_container_width=True, key=f"close_truck_dialog_{truck['id']}"):
        st.rerun()
    if ledger_column.button("Open truck ledger", use_container_width=True, key=f"dialog_ledger_{truck['id']}"):
        st.session_state["ledger_truck"] = truck["truck"]
        st.session_state["navigation_target"] = "Truck Ledger"
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
        st.markdown("### Live fleet inventory")
        st.caption("Search the complete fleet, compare stock positions and open one truck for detailed control.")

        working = fleet.copy()
        working["balance"] = pd.to_numeric(working["balance"], errors="coerce").fillna(0.0)
        working["capacity_liters"] = pd.to_numeric(working["capacity_liters"], errors="coerce").fillna(0.0)
        working["minimum_stock_liters"] = pd.to_numeric(working["minimum_stock_liters"], errors="coerce").fillna(0.0)
        working["reorder_level_liters"] = pd.to_numeric(working["reorder_level_liters"], errors="coerce").fillna(0.0)
        working["available_space"] = (working["capacity_liters"] - working["balance"]).clip(lower=0)
        working["utilization"] = working.apply(
            lambda item: item["balance"] / item["capacity_liters"] * 100 if item["capacity_liters"] > 0 else 0.0,
            axis=1,
        )

        def stock_condition(item):
            if item["capacity_liters"] <= 0:
                return "SETUP REQUIRED"
            if item["balance"] < 0:
                return "NEGATIVE"
            if item["minimum_stock_liters"] > 0 and item["balance"] <= item["minimum_stock_liters"]:
                return "CRITICAL"
            if item["reorder_level_liters"] > 0 and item["balance"] <= item["reorder_level_liters"]:
                return "REORDER"
            return "HEALTHY"

        working["stock_condition"] = working.apply(stock_condition, axis=1)

        search_col, status_col, condition_col, product_col = st.columns([2.2, 1.15, 1.15, 1.25])
        search = search_col.text_input(
            "Search truck",
            placeholder="Type plate number, code or emirate…",
            key="fleet_inventory_search",
        ).strip()
        status_options = ["All statuses"] + sorted(working["operational_status"].dropna().unique().tolist())
        selected_status = status_col.selectbox("Operating status", status_options, key="fleet_status_filter")
        condition_options = ["All stock levels", "CRITICAL", "REORDER", "HEALTHY", "NEGATIVE", "SETUP REQUIRED"]
        selected_condition = condition_col.selectbox("Stock level", condition_options, key="fleet_condition_filter")
        product_options = ["All products"] + sorted(working["product"].dropna().unique().tolist())
        selected_product = product_col.selectbox("Product", product_options, key="fleet_product_filter")

        view = working.copy()
        if search:
            normalized = " ".join(search.upper().split())
            compact = normalized.replace(" ", "")
            truck_text = view["truck"].fillna("").str.upper()
            view = view[truck_text.str.contains(normalized, regex=False) |
                        truck_text.str.replace(" ", "", regex=False).str.contains(compact, regex=False)]
        if selected_status != "All statuses":
            view = view[view["operational_status"] == selected_status]
        if selected_condition != "All stock levels":
            view = view[view["stock_condition"] == selected_condition]
        if selected_product != "All products":
            view = view[view["product"] == selected_product]

        result_col, sort_col = st.columns([3, 1])
        result_col.markdown(f"**{len(view):,} truck{'s' if len(view) != 1 else ''} found**")
        sort_choice = sort_col.selectbox(
            "Sort fleet",
            ["Truck number", "Lowest stock first", "Highest stock first", "Highest utilization"],
            label_visibility="collapsed",
            key="fleet_sort",
        )
        if sort_choice == "Lowest stock first":
            view = view.sort_values(["balance", "truck"])
        elif sort_choice == "Highest stock first":
            view = view.sort_values(["balance", "truck"], ascending=[False, True])
        elif sort_choice == "Highest utilization":
            view = view.sort_values(["utilization", "truck"], ascending=[False, True])
        else:
            view = view.sort_values("truck")

        if view.empty:
            st.warning("No trucks match the current search and filters.")
            return

        st.markdown("""
        <style>
        .fleet-row-truck{font-size:.98rem;font-weight:790;color:#101828;letter-spacing:-.02em;margin-top:.18rem}.fleet-row-sub{font-size:.66rem;color:#667085;margin-top:.18rem}
        .fleet-row-label{font-size:.56rem;color:#98A2B3;text-transform:uppercase;letter-spacing:.07em;font-weight:850;margin-top:.12rem}.fleet-row-value{font-size:1rem;color:#101828;font-weight:780;margin-top:.2rem}.fleet-row-value small{font-size:.65rem;color:#667085}
        .fleet-badge{display:inline-block;font-size:.57rem;font-weight:850;letter-spacing:.07em;padding:.31rem .48rem;border-radius:999px;white-space:nowrap;margin-top:.28rem}
        .fleet-badge.healthy{background:#ECFDF3;color:#027A48}.fleet-badge.reorder{background:#FFFAEB;color:#B54708}.fleet-badge.critical,.fleet-badge.negative{background:#FEF3F2;color:#B42318}.fleet-badge.setup-required{background:#F2F4F7;color:#475467}
        .fleet-row-track{height:8px;border-radius:999px;background:#EAECF0;overflow:hidden;margin:.48rem 0 .26rem}.fleet-row-fill{height:100%;border-radius:999px;background:linear-gradient(90deg,#8C1C1C,#C43A3A)}
        .fleet-row-caption{display:flex;justify-content:space-between;color:#667085;font-size:.6rem}
        </style>
        """, unsafe_allow_html=True)

        st.caption("Scroll through the filtered fleet. Each line is one live truck inventory position.")
        with st.container(height=650, border=False):
            for _, card in view.iterrows():
                condition = str(card["stock_condition"])
                badge_class = condition.lower().replace(" ", "-")
                utilization = float(card["utilization"])
                bar_width = max(0.0, min(utilization, 100.0))
                last_movement = pd.to_datetime(card["last_movement"]).strftime("%d %b %Y") if pd.notna(card["last_movement"]) else "No activity"
                product_name = str(card["product"]) if pd.notna(card["product"]) else "Product not assigned"
                with st.container(border=True):
                    identity, inventory, gauge, available, reorder, activity, action = st.columns([1.55, 1.1, 2.1, .9, .9, 1.05, .82], vertical_alignment="center")
                    identity.markdown(
                        f'<div class="fleet-row-truck">{escape(str(card["truck"]))}</div>'
                        f'<div class="fleet-row-sub">{escape(product_name)} · {escape(str(card["operational_status"]).title())}</div>'
                        f'<span class="fleet-badge {badge_class}">{escape(condition)}</span>',
                        unsafe_allow_html=True,
                    )
                    inventory.markdown(f'<div class="fleet-row-label">Live inventory</div><div class="fleet-row-value">{float(card["balance"]):,.2f} <small>L</small></div>', unsafe_allow_html=True)
                    gauge.markdown(
                        f'<div class="fleet-row-label">Tank utilization</div><div class="fleet-row-track"><div class="fleet-row-fill" style="width:{bar_width:.1f}%"></div></div>'
                        f'<div class="fleet-row-caption"><span>{utilization:.1f}% full</span><span>{float(card["capacity_liters"]):,.0f} L capacity</span></div>',
                        unsafe_allow_html=True,
                    )
                    available.markdown(f'<div class="fleet-row-label">Available</div><div class="fleet-row-value">{float(card["available_space"]):,.0f} <small>L</small></div>', unsafe_allow_html=True)
                    reorder.markdown(f'<div class="fleet-row-label">Reorder at</div><div class="fleet-row-value">{float(card["reorder_level_liters"]):,.0f} <small>L</small></div>', unsafe_allow_html=True)
                    activity.markdown(f'<div class="fleet-row-label">Last movement</div><div class="fleet-row-value" style="font-size:.78rem">{escape(last_movement)}</div>', unsafe_allow_html=True)
                    if action.button("↗", key=f"view_fleet_row_{int(card['id'])}", help="Open truck details", use_container_width=True, type="primary"):
                        edit_truck(conn, card)
