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
        .fleet-card{background:linear-gradient(145deg,#FFFFFF,#FAFBFC);border:1px solid #E4E7EC;border-radius:17px 17px 8px 8px;padding:17px 18px 14px;min-height:224px;box-shadow:0 9px 25px rgba(16,24,40,.055);position:relative;overflow:hidden;transition:.16s ease}
        .fleet-card:hover{border-color:#C7CDD6;box-shadow:0 15px 34px rgba(16,24,40,.10);transform:translateY(-2px)}
        .fleet-card:after{content:"";position:absolute;width:100px;height:100px;border-radius:50%;right:-52px;top:-52px;background:#8C1C1C0B}
        .fleet-top{display:flex;justify-content:space-between;align-items:flex-start;gap:.55rem}
        .fleet-number{font-size:1.02rem;font-weight:790;color:#101828;letter-spacing:-.025em}.fleet-product{font-size:.69rem;color:#667085;margin-top:.18rem}
        .fleet-badge{font-size:.58rem;font-weight:850;letter-spacing:.07em;padding:.32rem .48rem;border-radius:999px;white-space:nowrap}
        .fleet-badge.healthy{background:#ECFDF3;color:#027A48}.fleet-badge.reorder{background:#FFFAEB;color:#B54708}.fleet-badge.critical,.fleet-badge.negative{background:#FEF3F2;color:#B42318}.fleet-badge.setup-required{background:#F2F4F7;color:#475467}
        .fleet-balance-label{font-size:.6rem;color:#667085;font-weight:800;letter-spacing:.09em;text-transform:uppercase;margin-top:1rem}.fleet-balance{font-size:1.62rem;color:#101828;font-weight:800;letter-spacing:-.045em;margin-top:.08rem}.fleet-balance small{font-size:.72rem;color:#667085;font-weight:700;letter-spacing:0}
        .tank-track{height:8px;border-radius:999px;background:#EAECF0;overflow:hidden;margin:.75rem 0 .32rem}.tank-fill{height:100%;border-radius:999px;background:linear-gradient(90deg,#8C1C1C,#C43A3A)}
        .tank-caption{display:flex;justify-content:space-between;color:#667085;font-size:.62rem}
        .fleet-facts{display:grid;grid-template-columns:1fr 1fr 1fr;gap:.45rem;border-top:1px solid #EAECF0;margin-top:.85rem;padding-top:.72rem}.fleet-facts span{display:block;color:#98A2B3;font-size:.55rem;text-transform:uppercase;font-weight:800;letter-spacing:.05em}.fleet-facts b{display:block;color:#344054;font-size:.72rem;margin-top:.13rem}
        </style>
        """, unsafe_allow_html=True)

        page_size = 9
        page_count = max(1, (len(view) + page_size - 1) // page_size)
        current_page = min(max(int(st.session_state.get("fleet_gallery_page", 1)), 1), page_count)
        st.session_state["fleet_gallery_page"] = current_page
        page_start = (current_page - 1) * page_size
        gallery = view.iloc[page_start:page_start + page_size]

        for row_start in range(0, len(gallery), 3):
            card_columns = st.columns(3)
            for card_column, (_, card) in zip(card_columns, gallery.iloc[row_start:row_start + 3].iterrows()):
                condition = str(card["stock_condition"])
                badge_class = condition.lower().replace(" ", "-")
                utilization = float(card["utilization"])
                bar_width = max(0.0, min(utilization, 100.0))
                last_movement = pd.to_datetime(card["last_movement"]).strftime("%d %b %Y") if pd.notna(card["last_movement"]) else "No activity"
                with card_column:
                    st.markdown(
                        f'<div class="fleet-card"><div class="fleet-top"><div><div class="fleet-number">{escape(str(card["truck"]))}</div>'
                        f'<div class="fleet-product">{escape(str(card["product"] or "Product not assigned"))} · {escape(str(card["operational_status"]).title())}</div></div>'
                        f'<span class="fleet-badge {badge_class}">{escape(condition)}</span></div>'
                        f'<div class="fleet-balance-label">Live inventory</div><div class="fleet-balance">{float(card["balance"]):,.2f} <small>L</small></div>'
                        f'<div class="tank-track"><div class="tank-fill" style="width:{bar_width:.1f}%"></div></div>'
                        f'<div class="tank-caption"><span>{utilization:.1f}% full</span><span>{float(card["capacity_liters"]):,.0f} L capacity</span></div>'
                        f'<div class="fleet-facts"><div><span>Available</span><b>{float(card["available_space"]):,.0f} L</b></div>'
                        f'<div><span>Reorder at</span><b>{float(card["reorder_level_liters"]):,.0f} L</b></div>'
                        f'<div><span>Last movement</span><b>{escape(last_movement)}</b></div></div></div>',
                        unsafe_allow_html=True,
                    )
                    if st.button("View truck", key=f"view_fleet_card_{int(card['id'])}", use_container_width=True):
                        st.session_state["fleet_inspector_truck"] = card["truck"]
                        st.rerun()

        page_left, page_status, page_right = st.columns([1, 3, 1])
        if page_left.button("← Previous", disabled=current_page <= 1, use_container_width=True, key="fleet_previous_page"):
            st.session_state["fleet_gallery_page"] = current_page - 1
            st.rerun()
        page_status.markdown(f"<div style='text-align:center;color:#667085;padding:.7rem'>Page <b>{current_page}</b> of <b>{page_count}</b> · showing {page_start + 1}–{min(page_start + page_size, len(view))} of {len(view)}</div>", unsafe_allow_html=True)
        if page_right.button("Next →", disabled=current_page >= page_count, use_container_width=True, key="fleet_next_page"):
            st.session_state["fleet_gallery_page"] = current_page + 1
            st.rerun()

        st.markdown("#### Truck inspector")
        selected_truck = st.selectbox(
            "Select a truck for full details",
            view["truck"].tolist(),
            key="fleet_inspector_truck",
        )
        row = view[view["truck"] == selected_truck].iloc[0]
        balance = float(row["balance"])
        capacity = float(row["capacity_liters"])
        utilization = float(row["utilization"])
        available = float(row["available_space"])

        with st.container(border=True):
            heading, profile_action, ledger_action = st.columns([3.2, 1, 1])
            heading.markdown(f"### {row['truck']}")
            heading.caption(f"{row['product'] or 'Product not assigned'} · {row['operational_status'].title()} · {row['stock_condition'].title()}")
            if profile_action.button("Edit profile", key=f"edit_profile_{row['id']}", use_container_width=True):
                edit_truck(conn, row)
            if ledger_action.button("Open ledger", key=f"open_ledger_{row['id']}", use_container_width=True, type="primary"):
                st.session_state["ledger_truck"] = row["truck"]
                st.session_state["navigation_target"] = "Truck Ledger"
                st.rerun()

            detail_columns = st.columns(6)
            detail_columns[0].metric("On hand", f"{balance:,.2f} L")
            detail_columns[1].metric("Capacity", f"{capacity:,.0f} L")
            detail_columns[2].metric("Available", f"{available:,.0f} L")
            detail_columns[3].metric("Utilization", f"{utilization:,.1f}%")
            detail_columns[4].metric("Reorder at", f"{float(row['reorder_level_liters']):,.0f} L")
            detail_columns[5].metric("Minimum", f"{float(row['minimum_stock_liters']):,.0f} L")
            last_movement = row["last_movement"] if pd.notna(row["last_movement"]) else "No movements"
            st.progress(max(0.0, min(utilization / 100, 1.0)), text=f"{row['stock_condition'].title()} · Last movement: {last_movement}")
            if row["notes"]:
                st.caption(f"Notes: {row['notes']}")
