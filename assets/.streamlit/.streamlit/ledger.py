import streamlit as st
import pandas as pd
import io

def render_ledger(conn, truck_dict, truck_list):

    st.title("📘 Truck Ledger (Accounting View)")

    if not truck_list:
        st.warning("No trucks available")
        return

    # =============================
    # SELECT TRUCK + DATE FILTER
    # =============================

    col1, col2, col3 = st.columns([3,2,2])

    selected_truck = col1.selectbox("Select Truck", truck_list)
    from_date = col2.date_input("From Date")
    to_date = col3.date_input("To Date")

    truck_id = truck_dict[selected_truck]

    # =============================
    # GET GLOBAL PRICING
    # =============================

    settings_df = pd.read_sql_query("SELECT * FROM settings LIMIT 1", conn)

    cost_price = settings_df.iloc[0]["cost_per_liter"]
    selling_price = settings_df.iloc[0]["selling_price_per_liter"]

    # =============================
    # OPENING BALANCE (LITERS)
    # =============================

    opening_query = """
        SELECT 
            SUM(CASE WHEN type='IN' THEN liters ELSE 0 END) -
            SUM(CASE WHEN type='OUT' THEN liters ELSE 0 END)
        FROM transactions
        WHERE truck_id = %s
        AND date < %s
    """

    opening_df = pd.read_sql_query(
        opening_query,
        conn,
        params=[truck_id, str(from_date)]
    )

    opening_balance = opening_df.iloc[0, 0] or 0

    st.metric("Opening Balance (Liters)", f"{opening_balance:,.2f} L")

    st.markdown("---")

    # =============================
    # FETCH TRANSACTIONS
    # =============================

    ledger_query = """
        SELECT 
            date,
            type,
            liters,
            COALESCE(created_by, 'System') AS created_by
        FROM transactions
        WHERE truck_id = %s
        AND date BETWEEN %s AND %s
        ORDER BY date
    """

    ledger_df = pd.read_sql_query(
        ledger_query,
        conn,
        params=[truck_id, str(from_date), str(to_date)]
    )

    if ledger_df.empty:
        st.info("No transactions in selected period")
        return

    # =============================
    # CALCULATIONS
    # =============================

    ledger_df["IN"] = ledger_df.apply(lambda x: x["liters"] if x["type"] == "IN" else 0, axis=1)
    ledger_df["OUT"] = ledger_df.apply(lambda x: x["liters"] if x["type"] == "OUT" else 0, axis=1)

    # Cost and Revenue
    ledger_df["Cost"] = ledger_df["IN"] * cost_price
    ledger_df["Revenue"] = ledger_df["OUT"] * selling_price

    # Profit per row
    ledger_df["Profit"] = ledger_df["Revenue"] - ledger_df["Cost"]

    # Running Balance (Liters)
    ledger_df["Net Liters"] = ledger_df["IN"] - ledger_df["OUT"]
    ledger_df["Running Balance"] = ledger_df["Net Liters"].cumsum() + opening_balance

    # Running Profit
    ledger_df["Running Profit"] = ledger_df["Profit"].cumsum()

    final_balance = ledger_df["Running Balance"].iloc[-1]
    final_profit = ledger_df["Running Profit"].iloc[-1]

    # =============================
    # DISPLAY LEDGER
    # =============================

    st.subheader("Ledger Details")

    display_df = ledger_df[
        ["date", "IN", "OUT", "Cost", "Revenue", "Profit", "Running Balance", "Running Profit", "created_by"]
    ]
    
    # Rename for cleaner table headers
    display_df = display_df.rename(columns={"created_by": "Recorded By"})

    st.dataframe(display_df, use_container_width=True)

    st.markdown("---")

    colA, colB = st.columns(2)

    colA.metric("Closing Balance (Liters)", f"{final_balance:,.2f} L")
    colB.metric("Total Profit", f"{final_profit:,.2f}")

    # =============================
    # EXPORT OPTION
    # =============================

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        display_df.to_excel(writer, index=False)

    output.seek(0)

    st.download_button(
        label="Download Ledger (Excel)",
        data=output,
        file_name=f"{selected_truck}_ledger.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
