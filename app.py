import pandas as pd
import streamlit as st

from auth import logout, require_login, require_role
from branding import get_company_profile
from historical_import import render_historical_import
from dashboard import render_dashboard
from database import get_connection, init_db
from ledger import render_ledger
from reconciliation import render_reconciliation
from procurement import render_procurement
from forecasting import render_forecasting
from master_reports import render_master_reports
from rbac import allowed_pages, ensure_rbac_schema
from settings import render_settings
from storage import render_storage
from storage_operations import render_storage_operations
from transactions import render_transactions
from transaction_control import render_transaction_control
from trucks import render_trucks
from ui import apply_theme, page_header, render_sidebar_brand
from users_admin import render_user_management
from approval_workflow import ensure_approval_schema, process_approval_escalations, render_approval_centre
from user_notifications import ensure_notification_schema, render_notifications, render_request_confirmation, unread_count
from valuation import ensure_valuation_schema, render_valuation
from period_close import ensure_period_close_schema, render_period_close
from document_centre import DOCUMENT_CENTRE_VERSION, ensure_document_schema, render_document_centre
from supplier_master import ensure_supplier_master_schema, render_supplier_master
from supplier_scorecards import ensure_scorecard_schema, render_supplier_scorecards
from product_quality import ensure_quality_schema, render_product_quality
from batch_aging import ensure_batch_aging_schema, render_batch_aging
from stock_reservations import ensure_reservation_schema, render_stock_reservations
from inventory_health import render_inventory_health
from storage_control import ensure_storage_control_schema, render_storage_control
from stock_transit import ensure_transit_schema, render_stock_transit
from receipt_costing import ensure_receipt_cost_schema, render_receipt_costing
from schema_bootstrap import initialize_application_schema


st.set_page_config(page_title="Fuel Inventory Control", page_icon="⛽", layout="wide", initial_sidebar_state="expanded")
conn = get_connection()
init_db(conn)
initialize_application_schema(conn)
company = get_company_profile(conn)
st.session_state["company_profile"] = company
apply_theme(company)
require_login(conn)
if not st.session_state.get("approval_escalation_checked"):
    process_approval_escalations(conn)
    st.session_state["approval_escalation_checked"] = True
render_sidebar_brand(company)

menu = {
    "Command Centre": "Dashboard",
    "Fuel Operations": "Transactions",
    "Fleet Inventory": "Manage Trucks",
    "Inventory Control": "Reconciliation",
    "Measurement & Loss Control": "Storage Control",
    "Transaction Control": "Transaction Control",
    "Depots & Storage": "Storage",
    "Storage Operations": "Storage Operations",
    "Stock in Transit": "Stock Transit",
    "Supplier Procurement": "Procurement",
    "Supplier Master": "Supplier Master",
    "Supplier Scorecards": "Supplier Scorecards",
    "Receipt Costing": "Receipt Costing",
    "Product & Quality": "Product Quality",
    "Batch Aging & FEFO": "Batch Aging",
    "Stock Commitments": "Stock Reservations",
    "Inventory Forecasting": "Forecasting",
    "Financial Valuation": "Valuation",
    "Month-End Closing": "Period Closing",
    "Inventory Health": "Inventory Health",
    "Evidence Centre": "Evidence Centre",
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
requested = st.query_params.get("page", "Command Centre")
navigation_target = st.session_state.pop("navigation_target", None)
if navigation_target in labels:
    st.session_state["main_navigation"] = navigation_target
    st.query_params["page"] = navigation_target
if "main_navigation" not in st.session_state or st.session_state["main_navigation"] not in labels:
    st.session_state["main_navigation"] = requested if requested in labels else labels[0]


def open_page(label):
    st.session_state["main_navigation"] = label
    st.query_params["page"] = label
    st.rerun()


active_page=st.session_state["main_navigation"]
if st.sidebar.button("⌂  Command Centre",use_container_width=True,type="primary" if active_page=="Command Centre" else "secondary",key="nav_command_centre"):
    open_page("Command Centre")

notice_total=unread_count(conn)
if notice_total:
    st.sidebar.info(f"🔔 {notice_total} unread notification{'s' if notice_total != 1 else ''}")

navigation_groups={
    "Stock Operations":["Fuel Operations","Fleet Inventory","Inventory Control","Measurement & Loss Control","Transaction Control"],
    "Storage Network":["Depots & Storage","Storage Operations","Stock in Transit"],
    "Supply & Quality":["Supplier Procurement","Supplier Master","Supplier Scorecards","Receipt Costing","Product & Quality","Batch Aging & FEFO"],
    "Planning & Finance":["Stock Commitments","Inventory Forecasting","Financial Valuation","Month-End Closing","Inventory Health"],
    "Control & Assurance":["Evidence Centre","Truck Ledger","Integration Inbox","Approvals","Notifications","Report Centre","Audit Centre"],
    "Administration":["Configuration","User Access"],
}
icons={"Fuel Operations":"⇅","Fleet Inventory":"▣","Inventory Control":"✓","Measurement & Loss Control":"≋","Transaction Control":"↺","Depots & Storage":"▦","Storage Operations":"⇵","Stock in Transit":"→","Supplier Procurement":"◇","Supplier Master":"◎","Supplier Scorecards":"◔","Receipt Costing":"€","Product & Quality":"⚗","Batch Aging & FEFO":"⌛","Stock Commitments":"◈","Inventory Forecasting":"∿","Financial Valuation":"◉","Month-End Closing":"▤","Inventory Health":"♥","Evidence Centre":"▧","Truck Ledger":"≡","Integration Inbox":"⇩","Approvals":"✔","Notifications":"●","Report Centre":"▥","Audit Centre":"⌕","Configuration":"⚙","User Access":"◇"}
for group,items in navigation_groups.items():
    visible=[item for item in items if item in labels]
    if not visible: continue
    with st.sidebar.expander(group,expanded=active_page in visible):
        for label in visible:
            if st.button(f"{icons.get(label,'·')}  {label}",key=f"nav_{label}",use_container_width=True,type="primary" if active_page==label else "secondary"):
                open_page(label)

selected=st.session_state["main_navigation"]
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
elif page == "Storage Control":
    render_storage_control(conn)
elif page == "Transaction Control":
    render_transaction_control(conn)
elif page == "Storage":
    render_storage(conn)
elif page == "Storage Operations":
    render_storage_operations(conn)
elif page == "Stock Transit":
    render_stock_transit(conn)
elif page == "Procurement":
    render_procurement(conn)
elif page == "Supplier Master":
    render_supplier_master(conn)
elif page == "Supplier Scorecards":
    render_supplier_scorecards(conn)
elif page == "Receipt Costing":
    render_receipt_costing(conn)
elif page == "Product Quality":
    render_product_quality(conn)
elif page == "Batch Aging":
    render_batch_aging(conn)
elif page == "Stock Reservations":
    render_stock_reservations(conn)
elif page == "Forecasting":
    render_forecasting(conn)
elif page == "Valuation":
    render_valuation(conn)
elif page == "Period Closing":
    render_period_close(conn)
elif page == "Inventory Health":
    render_inventory_health(conn)
elif page == "Evidence Centre":
    render_document_centre(conn)
elif page == "Reports":
    render_master_reports(conn)
elif page == "Ledger":
    page_header("Truck Ledger", "Trace every movement and running balance by vehicle.")
    render_ledger(conn, truck_dict, truck_list)
elif page == "Bulk Upload":
    page_header("Integration Inbox", "Reconcile historical and current outbound delivery files before inventory changes.")
    render_historical_import(conn)
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
