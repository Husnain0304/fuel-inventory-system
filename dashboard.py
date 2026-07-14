import streamlit as st
import pandas as pd
import io


def render_dashboard(conn, truck_dict, truck_list):

    st.title("FILLIT INVENTORY DASHBOARD")
    st.markdown("---")

    # =============================
    # FILTER SECTION
    # =============================
    st.subheader("⚙️ Filter Criteria")
    col1, col2, col3 = st.columns([2, 2, 3])

    from_date = col1.date_input("From Date")
    to_date = col2.date_input("To Date")

    selected_trucks = col3.multiselect(
        "Select Trucks (Leave empty for All)",
        truck_list
    )

    params = [str(from_date), str(to_date)]

    if selected_trucks:
        truck_ids = [truck_dict[t] for t in selected_trucks]
        placeholders = ",".join(["?"] * len(truck_ids))
        truck_filter_sql = f" AND transactions.truck_id IN ({placeholders}) "
        params.extend(truck_ids)
    else:
        truck_filter_sql = ""

    st.markdown("---")

    # =============================
    # GET GLOBAL PRICES
    # =============================
    settings_df = pd.read_sql_query("SELECT * FROM settings LIMIT 1", conn)

    cost_price = settings_df.iloc[0]["cost_per_liter"]
    selling_price = settings_df.iloc[0]["selling_price_per_liter"]
    minimum_stock = settings_df.iloc[0]["minimum_stock_level"]

    # =============================
    # SUMMARY TOTALS
    # =============================
    summary_query = f"""
        SELECT 
            SUM(CASE WHEN type='IN' THEN liters ELSE 0 END) as total_in,
            SUM(CASE WHEN type='OUT' THEN liters ELSE 0 END) as total_out
        FROM transactions
        WHERE date BETWEEN ? AND ? {truck_filter_sql}
    """

    summary_df = pd.read_sql_query(summary_query, conn, params=params)

    total_in = summary_df.iloc[0]["total_in"] or 0
    total_out = summary_df.iloc[0]["total_out"] or 0
    net_balance = total_in - total_out

    total_cost = total_in * cost_price
    total_revenue = total_out * selling_price
    profit = total_revenue - total_cost

    # =============================
    # DISPLAY METRICS
    # =============================
    st.subheader("📊 Core Performance Indicators")
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Uplift (IN)", f"{total_in:,.2f} L")
    c2.metric("Total Delivery (OUT)", f"{total_out:,.2f} L")
    c3.metric("Net Balance", f"{net_balance:,.2f} L")

    st.write("") # Spacing

    c4, c5, c6 = st.columns(3)
    c4.metric("Total Cost", f"AED {total_cost:,.2f}")
    c5.metric("Total Revenue", f"AED {total_revenue:,.2f}")
    c6.metric("Projected Profit", f"AED {profit:,.2f}")

    st.markdown("---")

    # =============================
    # INVENTORY MOVEMENT SUMMARY
    # =============================
    st.subheader("📦 Inventory Movement Summary")

    today_query = """
        SELECT 
            SUM(CASE WHEN type='IN' THEN liters ELSE 0 END) as today_in,
            SUM(CASE WHEN type='OUT' THEN liters ELSE 0 END) as today_out
        FROM transactions
        WHERE date = DATE('now')
    """

    week_query = """
        SELECT 
            SUM(CASE WHEN type='IN' THEN liters ELSE 0 END) as week_in,
            SUM(CASE WHEN type='OUT' THEN liters ELSE 0 END) as week_out
        FROM transactions
        WHERE date >= DATE('now','-7 day')
    """

    today_df = pd.read_sql_query(today_query, conn)
    week_df = pd.read_sql_query(week_query, conn)

    today_in = today_df.iloc[0]["today_in"] or 0
    today_out = today_df.iloc[0]["today_out"] or 0
    week_in = week_df.iloc[0]["week_in"] or 0
    week_out = week_df.iloc[0]["week_out"] or 0

    colA, colB, colC, colD = st.columns(4)

    colA.metric("Today IN", f"{today_in:,.2f} L")
    colB.metric("Today OUT", f"{today_out:,.2f} L")
    colC.metric("Last 7 Days IN", f"{week_in:,.2f} L")
    colD.metric("Last 7 Days OUT", f"{week_out:,.2f} L")

    st.markdown("---")

    # =============================
    # LIVE TRUCK BALANCE TABLE
    # =============================
    st.subheader("🚛 Live Truck Balance Overview")

    balance_query = """
        SELECT 
            trucks.emirate || ' ' || trucks.plate_code || ' ' || trucks.plate_number AS truck,
            SUM(CASE WHEN type='IN' THEN liters ELSE 0 END) -
            SUM(CASE WHEN type='OUT' THEN liters ELSE 0 END) as balance
        FROM transactions
        JOIN trucks ON transactions.truck_id = trucks.id
        GROUP BY trucks.id
        ORDER BY balance ASC
    """

    balance_df = pd.read_sql_query(balance_query, conn)

    if not balance_df.empty:
        def get_status(balance):
            if balance < minimum_stock:
                return "🔴 Critical"
            elif balance < (minimum_stock * 2):
                return "🟡 Low"
            else:
                return "🟢 Good"

        balance_df["Status"] = balance_df["balance"].apply(get_status)
        
        # Format balance for nicer readability
        formatted_df = balance_df.copy()
        formatted_df["balance"] = formatted_df["balance"].apply(lambda x: f"{x:,.2f} L")
        formatted_df = formatted_df.rename(columns={"truck": "Truck Name", "balance": "Remaining Fuel", "Status": "Stock Condition"})

        st.dataframe(formatted_df, use_container_width=True)
    else:
        st.info("No truck balances available.")

    st.markdown("---")

    # =============================
    # RUNNING BALANCE CHART
    # =============================
    st.subheader("📈 Running Balance Trends Over Time")

    running_query = f"""
        SELECT 
            date,
            SUM(CASE WHEN type='IN' THEN liters ELSE 0 END) as total_in,
            SUM(CASE WHEN type='OUT' THEN liters ELSE 0 END) as total_out
        FROM transactions
        WHERE date BETWEEN ? AND ? {truck_filter_sql}
        GROUP BY date
        ORDER BY date
    """

    running_df = pd.read_sql_query(running_query, conn, params=params)

    if not running_df.empty:
        running_df["Net"] = running_df["total_in"] - running_df["total_out"]
        running_df["Running Balance"] = running_df["Net"].cumsum()
        
        chart_data = running_df.set_index("date")[["Running Balance"]]
        st.line_chart(chart_data)
    else:
        st.info("No data available for chart.")

    st.markdown("---")

    # =============================
    # REFILL STATUS SUMMARY
    # =============================
    st.subheader("⛽ Refill Request Summary")

    refill_summary = pd.read_sql_query("""
        SELECT 
            SUM(CASE WHEN status='PENDING' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN status='APPROVED' THEN 1 ELSE 0 END) as approved,
            SUM(CASE WHEN status='REJECTED' THEN 1 ELSE 0 END) as rejected
        FROM refill_requests
    """, conn)

    pending = refill_summary.iloc[0]["pending"] or 0
    approved = refill_summary.iloc[0]["approved"] or 0
    rejected = refill_summary.iloc[0]["rejected"] or 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Pending Requests", f"{pending} Orders")
    c2.metric("Approved Requests", f"{approved} Approved")
    c3.metric("Rejected Requests", f"{rejected} Rejected")

    st.markdown("---")

    # =============================
    # EXPORT OPTION
    # =============================
    if not running_df.empty:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            running_df.to_excel(writer, index=False)

        output.seek(0)

        st.download_button(
            label="Download Dashboard Report (Excel)",
            data=output,
            file_name="dashboard_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )