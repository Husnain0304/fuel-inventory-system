import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta

def render_dashboard(conn, truck_dict, truck_list):
    st.title("⛽ FILLIT DIESEL — OPERATIONAL DASHBOARD")
    st.caption("Fleet Inventory, Supplier Uplifts & Demand Forecasting")
    st.markdown("---")

    # Reverse lookup dictionary for trucks
    truck_id_to_name = {v: k for k, v in truck_dict.items()}

    # Fetch cursor for direct SQL queries
    cursor = conn.cursor()

    # Ensure supplier column exists on transactions table for safety
    cursor.execute("""
        ALTER TABLE transactions 
        ADD COLUMN IF NOT EXISTS supplier TEXT;
    """)
    conn.commit()

    # =========================================================================
    # SECTION 1: LIVE TRUCK INVENTORY & SIMPLE BALANCE LOOKUP
    # =========================================================================
    st.subheader("🚚 1. Live Truck Inventory & Fleet Balances")
    
    # Global Fleet Balance Query
    bal_query = """
        SELECT 
            t.truck_id,
            SUM(CASE WHEN t.type = 'IN' THEN t.liters ELSE 0 END) AS total_in,
            SUM(CASE WHEN t.type = 'OUT' THEN t.liters ELSE 0 END) AS total_out,
            SUM(CASE WHEN t.type = 'IN' THEN t.liters ELSE 0 END) -
            SUM(CASE WHEN t.type = 'OUT' THEN t.liters ELSE 0 END) AS current_balance
        FROM transactions t
        GROUP BY t.truck_id
    """
    cursor.execute(bal_query)
    bal_rows = cursor.fetchall()
    
    fleet_bal_df = pd.DataFrame(bal_rows, columns=["truck_id", "total_in", "total_out", "current_balance"])
    if not fleet_bal_df.empty:
        fleet_bal_df["truck"] = fleet_bal_df["truck_id"].map(truck_id_to_name)
    else:
        fleet_bal_df = pd.DataFrame(columns=["truck_id", "total_in", "total_out", "current_balance", "truck"])

    total_live_stock = fleet_bal_df["current_balance"].sum() if not fleet_bal_df.empty else 0.0

    # Section Top Metric Summary
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Fleet Current Balance", f"{total_live_stock:,.2f} L")
    m2.metric("Active Operating Trucks", len(fleet_bal_df[fleet_bal_df["current_balance"] > 0]))
    m3.metric("Total System Inflow (Uplifted)", f"{fleet_bal_df['total_in'].sum():,.2f} L" if not fleet_bal_df.empty else "0.00 L")

    # Filters for Inventory Table
    with st.expander("🔍 Filter Inventory Table", expanded=True):
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        inv_start = col_f1.date_input("Start Date", value=None, key="inv_start")
        inv_end = col_f2.date_input("End Date", value=None, key="inv_end")
        selected_truck = col_f3.selectbox("Filter Truck", ["All Trucks"] + truck_list, key="inv_truck")
        min_balance_filter = col_f4.number_input("Min Current Liters", value=0.0, step=100.0, key="inv_liters")

    # Transaction-filtered inventory building if dates/trucks selected
    filtered_inv_query = """
        SELECT 
            t.truck_id,
            SUM(CASE WHEN t.type = 'IN' THEN t.liters ELSE 0 END) AS in_liters,
            SUM(CASE WHEN t.type = 'OUT' THEN t.liters ELSE 0 END) AS out_liters,
            SUM(CASE WHEN t.type = 'IN' THEN t.liters ELSE 0 END) -
            SUM(CASE WHEN t.type = 'OUT' THEN t.liters ELSE 0 END) AS balance
        FROM transactions t
        WHERE 1=1
    """
    f_params = []
    if inv_start:
        filtered_inv_query += " AND t.date >= %s"
        f_params.append(str(inv_start))
    if inv_end:
        filtered_inv_query += " AND t.date <= %s"
        f_params.append(str(inv_end))
    if selected_truck != "All Trucks":
        filtered_inv_query += " AND t.truck_id = %s"
        f_params.append(truck_dict[selected_truck])

    filtered_inv_query += " GROUP BY t.truck_id"

    cursor.execute(filtered_inv_query, tuple(f_params))
    f_rows = cursor.fetchall()
    disp_inv_df = pd.DataFrame(f_rows, columns=["truck_id", "in_liters", "out_liters", "balance"])

    if not disp_inv_df.empty:
        disp_inv_df["truck"] = disp_inv_df["truck_id"].map(truck_id_to_name)
        disp_inv_df = disp_inv_df[disp_inv_df["balance"] >= min_balance_filter]
        disp_inv_df = disp_inv_df[["truck", "in_liters", "out_liters", "balance"]]
    else:
        disp_inv_df = pd.DataFrame(columns=["truck", "in_liters", "out_liters", "balance"])

    st.dataframe(
        disp_inv_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "truck": st.column_config.TextColumn("Truck Name / Plate"),
            "in_liters": st.column_config.NumberColumn("Total Uplifted (IN)", format="%.2f L"),
            "out_liters": st.column_config.NumberColumn("Total Delivered (OUT)", format="%.2f L"),
            "balance": st.column_config.NumberColumn("Live Inventory Balance", format="%.2f L")
        }
    )

    st.markdown("---")

    # =========================================================================
    # SECTION 2: SUPPLIER-WISE & DATE-WISE UPLIFTED INVENTORY
    # =========================================================================
    st.subheader("⚓ 2. Total Uplifted Diesel (Supplier & Truck Wise)")

    col_up1, col_up2, col_up3, col_up4 = st.columns(4)
    up_start_date = col_up1.date_input("From Date", value=date.today() - timedelta(days=30), key="up_start")
    up_end_date = col_up2.date_input("To Date", value=date.today(), key="up_end")
    up_truck_filter = col_up3.selectbox("Filter Truck", ["All Trucks"] + truck_list, key="up_truck")
    
    # Fetch distinct suppliers from DB for filtering
    cursor.execute("SELECT DISTINCT COALESCE(supplier, 'Unspecified Supplier') FROM transactions WHERE type='IN'")
    supplier_options = ["All Suppliers"] + [row[0] for row in cursor.fetchall() if row[0]]
    up_supplier_filter = col_up4.selectbox("Filter Supplier", supplier_options, key="up_supplier")

    up_query = """
        SELECT 
            t.date,
            t.truck_id,
            COALESCE(t.supplier, 'Unspecified Supplier') AS supplier,
            SUM(t.liters) AS uplifted_liters
        FROM transactions t
        WHERE t.type = 'IN' AND t.date BETWEEN %s AND %s
    """
    up_params = [str(up_start_date), str(up_end_date)]

    if up_truck_filter != "All Trucks":
        up_query += " AND t.truck_id = %s"
        up_params.append(truck_dict[up_truck_filter])

    if up_supplier_filter != "All Suppliers":
        up_query += " AND t.supplier = %s"
        up_params.append(up_supplier_filter)

    up_query += " GROUP BY t.date, t.truck_id, t.supplier ORDER BY t.date DESC;"

    cursor.execute(up_query, tuple(up_params))
    up_rows = cursor.fetchall()
    uplift_summary_df = pd.DataFrame(up_rows, columns=["date", "truck_id", "supplier", "uplifted_liters"])

    if not uplift_summary_df.empty:
        uplift_summary_df["truck"] = uplift_summary_df["truck_id"].map(truck_id_to_name)
        
        # Aggregate totals card
        total_uplifted_in_period = uplift_summary_df["uplifted_liters"].sum()
        st.info(f"💡 **Total Fuel Uplifted ({up_start_date} to {up_end_date}):** `{total_uplifted_in_period:,.2f} Liters` across selected suppliers/trucks.")

        # Breakdown pivot table
        st.write("#### Supplier & Truck Uplift Breakdown Table")
        display_up_df = uplift_summary_df[["date", "supplier", "truck", "uplifted_liters"]]
        st.dataframe(
            display_up_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "date": st.column_config.DateColumn("Uplift Date"),
                "supplier": st.column_config.TextColumn("Fuel Supplier"),
                "truck": st.column_config.TextColumn("Receiving Truck"),
                "uplifted_liters": st.column_config.NumberColumn("Uplifted Liters", format="%.2f L")
            }
        )
    else:
        st.warning("No uplift records found for the selected date range and supplier/truck filters.")

    st.markdown("---")

    # =========================================================================
    # SECTION 3: INVENTORY FORECAST & AD-HOC DELIVERY PLANNING
    # =========================================================================
    st.subheader("🔮 3. Simple Inventory Forecast & Ad-Hoc Delivery Planning")

    # Historical consumption baseline selector
    col_fc1, col_fc2, col_fc3 = st.columns(3)
    baseline_range = col_fc1.selectbox("Forecast Consumption Baseline", ["Last 7 Days Average", "Last 30 Days Average"])
    forecast_days = col_fc2.number_input("Forecast Days (e.g. 7 for Next Week)", min_value=1, max_value=30, value=7, step=1)
    
    # Calculate baseline daily consumption rate
    lookback_days = 7 if baseline_range == "Last 7 Days Average" else 30
    baseline_start_date = (date.today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT SUM(liters) FROM transactions 
        WHERE type = 'OUT' AND date >= %s
    """, (baseline_start_date,))
    out_row = cursor.fetchone()
    total_past_out = out_row[0] if out_row and out_row[0] is not None else 0.0

    avg_daily_consumption = total_past_out / float(lookback_days)
    col_fc3.metric(f"Avg Daily Outflow ({baseline_range})", f"{avg_daily_consumption:,.2f} L/day")

    st.markdown("#### ⚡ Ad-Hoc Delivery Simulator")
    col_ad1, col_ad2, col_ad3 = st.columns([2, 2, 3])
    adhoc_date = col_ad1.date_input("Ad-hoc Delivery Date", value=date.today() + timedelta(days=1), key="adhoc_date")
    adhoc_liters = col_ad2.number_input("Required Ad-Hoc Liters", min_value=0.0, value=0.0, step=500.0, key="adhoc_liters")
    adhoc_note = col_ad3.text_input("Ad-Hoc Customer / Site Note", placeholder="e.g. Urgent construction order")

    # Generate Forecast Table
    forecast_rows = []
    accumulated_req_no_adhoc = 0.0
    accumulated_req_with_adhoc = 0.0

    for day_idx in range(1, forecast_days + 1):
        target_day = date.today() + timedelta(days=day_idx)
        day_baseline_req = avg_daily_consumption

        # Apply ad-hoc on selected delivery date
        day_adhoc_req = adhoc_liters if (target_day == adhoc_date) else 0.0
        day_total_with_adhoc = day_baseline_req + day_adhoc_req

        accumulated_req_no_adhoc += day_baseline_req
        accumulated_req_with_adhoc += day_total_with_adhoc

        forecast_rows.append({
            "day": f"Day {day_idx}",
            "date": target_day.strftime("%Y-%m-%d"),
            "daily_req_no_adhoc": day_baseline_req,
            "daily_adhoc": day_adhoc_req,
            "daily_req_with_adhoc": day_total_with_adhoc,
            "cum_no_adhoc": accumulated_req_no_adhoc,
            "cum_with_adhoc": accumulated_req_with_adhoc
        })

    forecast_df = pd.DataFrame(forecast_rows)

    # Forecast Summary Cards
    st.markdown("#### 📊 Forecast Totals Summary")
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric(f"Total Required ({forecast_days} Days - No Ad-Hoc)", f"{accumulated_req_no_adhoc:,.2f} L")
    mc2.metric(f"Total Ad-Hoc Demand Added", f"{adhoc_liters:,.2f} L")
    mc3.metric(f"Total Required ({forecast_days} Days - WITH Ad-Hoc)", f"{accumulated_req_with_adhoc:,.2f} L", delta=f"+{adhoc_liters:,.2f} L" if adhoc_liters > 0 else None)

    # Day-by-Day Forecast Breakdown Table
    st.markdown(f"#### 🗓️ Day-by-Day Forecast ({forecast_days}-Day Detailed Breakdown)")
    st.dataframe(
        forecast_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "day": st.column_config.TextColumn("Day"),
            "date": st.column_config.DateColumn("Date"),
            "daily_req_no_adhoc": st.column_config.NumberColumn("Daily Req. (Without Ad-hoc)", format="%.2f L"),
            "daily_adhoc": st.column_config.NumberColumn("Ad-hoc Demand", format="%.2f L"),
            "daily_req_with_adhoc": st.column_config.NumberColumn("Daily Req. (With Ad-hoc)", format="%.2f L"),
            "cum_no_adhoc": st.column_config.NumberColumn("Cumulative Req. (Without Ad-hoc)", format="%.2f L"),
            "cum_with_adhoc": st.column_config.NumberColumn("Cumulative Req. (With Ad-hoc)", format="%.2f L")
        }
    )
