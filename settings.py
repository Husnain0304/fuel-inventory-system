import pandas as pd
import streamlit as st

from audit import record_event
from branding import get_company_profile, save_company_profile


def render_settings(conn, cursor):
    tabs = st.tabs(["Company & Branding", "Inventory Rules", "Modules"])
    with tabs[0]:
        current = get_company_profile(conn)
        st.subheader("Company and product identity")
        st.caption("These settings rebrand the application without changing any code.")
        with st.form("company_profile_form"):
            c1, c2 = st.columns(2)
            values = {
                "company_name": c1.text_input("Company name", current["company_name"]),
                "application_name": c2.text_input("Application name", current["application_name"]),
                "tagline": st.text_input("Short description", current["tagline"]),
                "primary_color": c1.color_picker("Primary colour", current["primary_color"]),
                "secondary_color": c2.color_picker("Secondary colour", current["secondary_color"]),
                "accent_color": c1.color_picker("Success/accent colour", current["accent_color"]),
                "currency": c2.text_input("Currency", current["currency"]),
                "timezone": c1.text_input("Time zone", current["timezone"]),
                "date_format": c2.selectbox("Date format", ["DD MMM YYYY", "DD/MM/YYYY", "YYYY-MM-DD"],
                                             index=["DD MMM YYYY", "DD/MM/YYYY", "YYYY-MM-DD"].index(current["date_format"]) if current["date_format"] in ["DD MMM YYYY", "DD/MM/YYYY", "YYYY-MM-DD"] else 0),
                "volume_unit": c1.selectbox("Volume unit", ["L", "US gal", "UK gal"], index=0),
                "report_footer": st.text_input("Report footer", current["report_footer"]),
            }
            if st.form_submit_button("Save company profile", type="primary"):
                save_company_profile(conn, values, st.session_state.get("user", "System"))
                record_event(conn, "UPDATE", "Configuration", "Company Profile", 1,
                             "Updated company branding and regional preferences", old_values=current, new_values=values)
                st.success("Company profile saved. The new branding is now active.")
                st.rerun()

    with tabs[1]:
        settings = pd.read_sql_query("SELECT * FROM settings ORDER BY id LIMIT 1", conn).iloc[0]
        with st.form("inventory_rules_form"):
            cost = st.number_input("Default cost per litre", min_value=0.0, value=float(settings["cost_per_liter"] or 0), format="%.3f")
            price = st.number_input("Default selling price per litre", min_value=0.0, value=float(settings["selling_price_per_liter"] or 0), format="%.3f")
            minimum = st.number_input("Default minimum stock level", min_value=0.0, value=float(settings["minimum_stock_level"] or 0), format="%.2f")
            if st.form_submit_button("Save inventory rules", type="primary"):
                cursor.execute("UPDATE settings SET cost_per_liter=%s, selling_price_per_liter=%s, minimum_stock_level=%s WHERE id=%s",
                               (cost, price, minimum, int(settings["id"])))
                conn.commit()
                record_event(conn, "UPDATE", "Configuration", "Inventory Rules", int(settings["id"]),
                             "Updated default inventory and pricing rules")
                st.success("Inventory rules updated.")

    with tabs[2]:
        st.subheader("Available modules")
        st.caption("Future modules are visible here but remain disabled until their database and workflows are completed.")
        modules = pd.read_sql_query("SELECT display_name, enabled, sort_order FROM module_settings ORDER BY sort_order", conn)
        st.dataframe(modules, use_container_width=True, hide_index=True,
                     column_config={"display_name":"Module", "enabled":"Available", "sort_order":None})
