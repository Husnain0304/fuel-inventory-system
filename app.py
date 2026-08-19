import pandas as pd
import streamlit as st

from auth import logout, require_login, require_role
from branding import get_company_profile
from bulk_upload import render_bulk_upload
from dashboard import render_dashboard
from database import get_connection, init_db
from ledger import render_ledger
from reconciliation import render_reconciliation
from procurement import render_procurement
from forecasting import render_forecasting
from master_reports import render_master_reports
from rbac import allowed_pages, ensure_rbac_schema
from reports import render_reports
from settings import render_settings
from storage import render_storage
from storage_operations import render_storage_operations
from transactions import render_transactions
from transaction_control import render_transaction_control
from trucks import render_trucks
from ui import apply_theme, page_header, render_sidebar_brand
from users_admin import render_user_management
from approval_workflow import ensure_approval_schema, render_approval_centre
from user_notifications import ensure_notification_schema, render_notifications, render_request_confirmation, unread_count


st.set_page_config(page_title="Fuel Inventory Control", page_icon="⛽", layout="wide", initial_sidebar_state="expanded")
conn = get_connection()
init_db(conn)
ensure_rbac_schema(conn)
ensure_approval_schema(conn)
company = get_company_profile(conn)
st.session_state["company_profile"] = company
apply_theme(company)
require_login(conn)
if not st.session_state.get("notification_schema_ready"):
    ensure_notification_schema(conn)
    st.session_state["notification_schema_ready"] = True
render_sidebar_brand(company)

menu = {
    "Command Centre": "Dashboard",
    "Fuel Operations": "Transactions",
    "Fleet Inventory": "Manage Trucks",
    "Inventory Control": "Reconciliation",
    "Transaction Control": "Transaction Control",
    "Depots & Storage": "Storage",
    "Storage Operations": "Storage Operations",
    "Supplier Procurement": "Procurement",
    "Inventory Forecasting": "Forecasting",
    "Truck Ledger": "Ledger",
    "Integration Inbox": "Bulk Upload",
    "Approvals": "Refill Approvals",
    "Notifications": "Notifications",
    "Report Centre": "Reports",
    "Audit Centre": "Audit Log",
    "Configuration": "Settings",
}
menu["User Access"] = "Manage Users"
permitted=allowed_pages(st.session_state.get("role","VIEWER"))
menu={label:page_name for label,page_name in menu.items() if label in permitted}

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

notice_total=unread_count(conn)
if notice_total:
    st.sidebar.info(f"🔔 {notice_total} unread notification{'s' if notice_total != 1 else ''}")

selected = st.sidebar.radio("WORKSPACE", labels, key="main_navigation", on_change=remember_page)
page = menu[selected]
render_request_confirmation()
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
elif page == "Reconciliation":
    render_reconciliation(conn)
elif page == "Transaction Control":
    render_transaction_control(conn)
elif page == "Storage":
    render_storage(conn)
elif page == "Storage Operations":
    render_storage_operations(conn)
elif page == "Procurement":
    render_procurement(conn)
elif page == "Forecasting":
    render_forecasting(conn)
elif page == "Reports":
    render_master_reports(conn)
elif page == "Ledger":
    page_header("Truck Ledger", "Trace every movement and running balance by vehicle.")
    render_ledger(conn, truck_dict, truck_list)
elif page == "Bulk Upload":
    page_header("Integration Inbox", "Validate external delivery data before it changes inventory.")
    render_bulk_upload(conn, cursor, truck_dict, truck_list)
elif page == "Refill Approvals":
    render_approval_centre(conn)
elif page == "Notifications":
    render_notifications(conn)
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
