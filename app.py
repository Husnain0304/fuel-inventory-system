import pandas as pd
import streamlit as st

from auth import logout, require_login, require_role
from branding import get_company_profile
from bulk_upload import render_bulk_upload
from dashboard import render_dashboard
from database import get_connection, init_db
from ledger import render_ledger
from reports import render_reports
from settings import render_settings
from transactions import render_transactions
from trucks import render_trucks
from ui import apply_theme, page_header, render_sidebar_brand
from users_admin import render_user_management


st.set_page_config(page_title="Fuel Inventory Control", page_icon="⛽", layout="wide", initial_sidebar_state="expanded")
conn = get_connection()
init_db(conn)
company = get_company_profile(conn)
st.session_state["company_profile"] = company
apply_theme(company)
require_login(conn)
render_sidebar_brand(company)

menu = {
    "Command Centre": "Dashboard",
    "Fuel Operations": "Transactions",
    "Fleet Inventory": "Manage Trucks",
    "Truck Ledger": "Ledger",
    "Integration Inbox": "Bulk Upload",
    "Approvals": "Refill Approvals",
    "Report Centre": "Reports",
    "Audit Centre": "Audit Log",
    "Configuration": "Settings",
}
if st.session_state.get("role") == "ADMIN":
    menu["User Access"] = "Manage Users"

labels = list(menu)
requested = st.query_params.get("page", labels[0])
navigation_target = st.session_state.pop("navigation_target", None)
if navigation_target in labels:
    st.session_state["main_navigation"] = navigation_target
    st.query_params["page"] = navigation_target
if "main_navigation" not in st.session_state or st.session_state["main_navigation"] not in labels:
    st.session_state["main_navigation"] = requested if requested in labels else labels[0]


def remember_page():
    st.query_params["page"] = st.session_state["main_navigation"]


if st.sidebar.button("⌂  Home · Command Centre", use_container_width=True, type="primary"):
    st.session_state["main_navigation"] = "Command Centre"
    st.query_params["page"] = "Command Centre"

selected = st.sidebar.radio("WORKSPACE", labels, key="main_navigation", on_change=remember_page)
page = menu[selected]
st.sidebar.divider()
st.sidebar.caption(f"Signed in as {st.session_state['user']} · {st.session_state['role'].title()}")
if st.sidebar.button("Sign out", use_container_width=True):
    logout(conn)

cursor = conn.cursor()
cursor.execute("SELECT id, emirate, plate_code, plate_number FROM trucks ORDER BY emirate, plate_code, plate_number")
truck_rows = cursor.fetchall()
truck_dict = {f"{row[1]} {row[2]} {row[3]}": row[0] for row in truck_rows}
truck_list = list(truck_dict)

if page == "Dashboard":
    render_dashboard(conn, truck_dict, truck_list)
elif page == "Transactions":
    render_transactions(conn, cursor, truck_dict, truck_list)
elif page == "Manage Trucks":
    page_header("Fleet Inventory", "Register vehicles and manage truck-level stock controls.")
    render_trucks(conn, cursor)
elif page == "Reports":
    page_header("Report Centre", "Review, filter and export inventory and operational performance.")
    render_reports(conn, truck_dict, truck_list)
elif page == "Ledger":
    page_header("Truck Ledger", "Trace every movement and running balance by vehicle.")
    render_ledger(conn, truck_dict, truck_list)
elif page == "Bulk Upload":
    page_header("Integration Inbox", "Validate external delivery data before it changes inventory.")
    render_bulk_upload(conn, cursor, truck_dict, truck_list)
elif page == "Refill Approvals":
    from approvals import render_approvals
    render_approvals(conn, cursor)
elif page == "Audit Log":
    page_header("Audit Centre", "Investigate who performed an action, when it happened and what changed.")
    c1, c2, c3 = st.columns([1, 1, 2])
    limit = c1.selectbox("Rows", [100, 250, 500, 1000], index=0)
    user_filter = c2.text_input("User contains")
    action_filter = c3.text_input("Search action, module, record or description")
    events = pd.read_sql_query(
        """SELECT occurred_at AS "Date & Time", username AS "User", user_role AS "Role",
                  module AS "Module", action AS "Action", entity_type AS "Record Type",
                  entity_id AS "Record ID", description AS "Description", status AS "Status",
                  severity AS "Severity", business_location AS "Location"
           FROM audit_events ORDER BY occurred_at DESC LIMIT %s""", conn, params=[limit]
    )
    if user_filter:
        events = events[events["User"].str.contains(user_filter, case=False, na=False)]
    if action_filter:
        searchable = events.astype(str).agg(" ".join, axis=1)
        events = events[searchable.str.contains(action_filter, case=False, na=False)]
    st.dataframe(events, use_container_width=True, hide_index=True, height=520)
    with st.expander("Legacy activity history"):
        legacy = pd.read_sql_query('SELECT timestamp AS "Date & Time", "user" AS "User", action AS "Action" FROM audit_log ORDER BY id DESC LIMIT %s', conn, params=[limit])
        st.dataframe(legacy, use_container_width=True, hide_index=True)
elif page == "Settings":
    require_role("ADMIN")
    page_header("Configuration", "Change branding, inventory rules and product modules without editing code.")
    render_settings(conn, cursor)
elif page == "Manage Users":
    require_role("ADMIN")
    page_header("User Access", "Create accounts and control application permissions.")
    render_user_management(conn, cursor)
