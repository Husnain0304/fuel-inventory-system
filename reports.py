import streamlit as st
import pandas as pd
import io


def render_reports(conn, truck_dict, truck_list):

    st.title("📅 Reports")

    col1, col2 = st.columns(2)

    from_date = col1.date_input("From Date")
    to_date = col2.date_input("To Date")

    st.markdown("---")
    st.subheader("📊 Monthly Profit Summary")

    # Get pricing
    settings_df = pd.read_sql_query("SELECT * FROM settings LIMIT 1", conn)
    cost_price = settings_df.iloc[0]["cost_per_liter"]
    selling_price = settings_df.iloc[0]["selling_price_per_liter"]

    # Modified: SQLite strftime is replaced with PostgreSQL TO_CHAR
    monthly_query = """
        SELECT 
            TO_CHAR(CAST(date AS TIMESTAMP), 'YYYY-MM') as month,
            SUM(CASE WHEN type='IN' THEN liters ELSE 0 END) as total_in,
            SUM(CASE WHEN type='OUT' THEN liters ELSE 0 END) as total_out
        FROM transactions
        GROUP BY month
        ORDER BY month
    """

    monthly_df = pd.read_sql_query(monthly_query, conn)

    if not monthly_df.empty:

        monthly_df["Cost"] = monthly_df["total_in"] * cost_price
        monthly_df["Revenue"] = monthly_df["total_out"] * selling_price
        monthly_df["Profit"] = monthly_df["Revenue"] - monthly_df["Cost"]

        st.dataframe(monthly_df, use_container_width=True)

        st.line_chart(monthly_df.set_index("month")[["Profit"]])

        # Export
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            monthly_df.to_excel(writer, index=False)
        output.seek(0)

        st.download_button(
            label="Download Monthly Profit Report",
            data=output,
            file_name="monthly_profit_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    else:
        st.info("No data available for monthly summary.")

    # =============================
    # TRUCK SELECTION
    # =============================

    selected_trucks = st.multiselect(
        "Select Trucks (Leave empty for All)",
        truck_list
    )

    params = [str(from_date), str(to_date)]

    if selected_trucks:
        truck_ids = [truck_dict[t] for t in selected_trucks]
        # PostgreSQL uses '%s' as placeholders
        placeholders = ",".join(["%s"] * len(truck_ids))
        truck_filter_sql = f" AND transactions.truck_id IN ({placeholders}) "
        params.extend(truck_ids)
    else:
        truck_filter_sql = ""

    # =============================
    # SUMMARY TOTALS
    # =============================

    # Modified: Placeholders updated to %s
    summary_query = f"""
        SELECT 
            SUM(CASE WHEN type='IN' THEN liters ELSE 0 END) as total_in,
            SUM(CASE WHEN type='OUT' THEN liters ELSE 0 END) as total_out
        FROM transactions
        WHERE date BETWEEN %s AND %s {truck_filter_sql}
    """

    summary_df = pd.read_sql_query(summary_query, conn, params=params)

    total_in = summary_df.iloc[0]["total_in"] or 0
    total_out = summary_df.iloc[0]["total_out"] or 0
    net_balance = total_in - total_out

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Uplift (IN)", f"{total_in:,.2f} L")
    c2.metric("Total Delivery (OUT)", f"{total_out:,.2f} L")
    c3.metric("Net Balance", f"{net_balance:,.2f} L")

    st.markdown("---")

    # =============================
    # TRUCK-WISE REPORT
    # =============================

    # Modified: SQLite string concatenation '||' replaced with PostgreSQL CONCAT
    # Placeholders updated to %s
    report_query = f"""
        SELECT 
            CONCAT(trucks.emirate, ' ', trucks.plate_code, ' ', trucks.plate_number) AS truck,
            SUM(CASE WHEN type='IN' THEN liters ELSE 0 END) as total_in,
            SUM(CASE WHEN type='OUT' THEN liters ELSE 0 END) as total_out
        FROM transactions
        JOIN trucks ON transactions.truck_id = trucks.id
        WHERE date BETWEEN %s AND %s {truck_filter_sql}
        GROUP BY trucks.id, trucks.emirate, trucks.plate_code, trucks.plate_number
        ORDER BY truck
    """

    report_df = pd.read_sql_query(report_query, conn, params=params)

    if not report_df.empty:

        report_df["Net Balance"] = report_df["total_in"] - report_df["total_out"]

        st.subheader("Truck-wise Summary")
        st.dataframe(report_df, use_container_width=True)

        # =============================
        # DOWNLOAD OPTION
        # =============================

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            report_df.to_excel(writer, index=False)

        output.seek(0)

        st.download_button(
            label="Download Report (Excel)",
            data=output,
            file_name="truck_wise_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    else:
        st.info("No data available for selected range.")
