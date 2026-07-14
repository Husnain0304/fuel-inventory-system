import streamlit as st
import pandas as pd

def render_settings(conn, cursor):

    st.title("⚙️ Global Settings")

    settings_df = pd.read_sql_query("SELECT * FROM settings LIMIT 1", conn)

    if settings_df.empty:
        st.error("Settings not initialized.")
        return

    current_cost = settings_df.iloc[0]["cost_per_liter"]
    current_price = settings_df.iloc[0]["selling_price_per_liter"]
    current_minimum = settings_df.iloc[0]["minimum_stock_level"]

    st.subheader("Global Pricing")

    new_cost = st.number_input(
        "Global Cost Price (per Liter)",
        value=float(current_cost),
        format="%.2f"
    )

    new_price = st.number_input(
        "Global Selling Price (per Liter)",
        value=float(current_price),
        format="%.2f"
    )

    st.markdown("---")

    st.subheader("Inventory Settings")

    new_minimum = st.number_input(
        "Minimum Stock Level (Liters)",
        value=float(current_minimum),
        format="%.2f"
    )

    if st.button("Update Settings"):
        cursor.execute(
            "UPDATE settings SET cost_per_liter=?, selling_price_per_liter=?, minimum_stock_level=?",
            (new_cost, new_price, new_minimum)
        )
        conn.commit()
        st.success("✅ Settings updated successfully")
        st.rerun()