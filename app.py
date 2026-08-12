import pandas as pd
import streamlit as st

from auth import logout, require_login, require_role
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


st.set_page_config(
    page_title="FILLIT | Fleet Fuel Control",
    page_icon="⛽",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()

conn = get_connection()
init_db(conn)
require_login(conn)

render_sidebar_brand()

menu = {
    "Overview": "Dashboard",
    "Fuel Operations": "Transactions",
    "Fleet": "Manage Trucks",
    "Insights": "Reports",
    "Truck Ledger": "Ledger",
    "Import Data": "Bulk Upload",
    "Approvals": "Refill Approvals",
    "Activity": "Audit Log",
    "Configuration": "Settings",
}

if st.session_state.get("role") == "ADMIN":
    menu["User Access"] = "Manage Users"

labels = list(menu)

if "main_navigation" not in st.session_state:
    requested_page = st.query_params.get("page", labels[0])

    if requested_page in labels:
        st.session_state["main_navigation"] = requested_page
    else:
        st.session_state["main_navigation"] = labels[0]


def remember_page():
    selected_page = st.session_state["main_navigation"]
    st.query_params["page"] = selected_page


selected = st.sidebar.radio(
    "WORKSPACE",
    labels,
    key="main_navigation",
    on_change=remember_page,
)

page = menu[selected]

st.sidebar.divider()

st.sidebar.caption(
    f"Signed in as {st.session_state['user']} · "
    f"{st.session_state['role'].title()}"
)

if st.sidebar.button("Sign out", use_container_width=True):
    logout(conn)

cursor = conn.cursor()

cursor.execute(
    """
    SELECT id, emirate, plate_code, plate_number
    FROM trucks
    ORDER BY emirate, plate_code, plate_number
    """
)

truck_rows = cursor.fetchall()

truck_dict = {
    f"{row[1]} {row[2]} {row[3]}": row[0]
    for row in truck_rows
}

truck_list = list(truck_dict)

if page == "Dashboard":
    render_dashboard(conn, truck_dict, truck_list)

elif page == "Transactions":
    render_transactions(
        conn,
        cursor,
        truck_dict,
        truck_list,
    )

elif page == "Manage Trucks":
    page_header(
        "Fleet",
        "Register vehicles and manage truck-level pricing.",
    )
    render_trucks(conn, cursor)

elif page == "Reports":
    page_header(
        "Reports",
        "Review fuel movement, cost, and operational performance.",
    )
    render_reports(
        conn,
        truck_dict,
        truck_list,
    )

elif page == "Ledger":
    page_header(
        "Truck Ledger",
        "Trace balances and movements by vehicle.",
    )
    render_ledger(
        conn,
        truck_dict,
        truck_list,
    )

elif page == "Bulk Upload":
    page_header(
        "Import Data",
        "Validate and import delivery records from Excel.",
    )
    render_bulk_upload(
        conn,
        cursor,
        truck_dict,
        truck_list,
    )

elif page == "Refill Approvals":
    from approvals import render_approvals

    render_approvals(conn, cursor)

elif page == "Audit Log":
    page_header(
        "Activity",
        "Review the latest recorded system actions.",
    )

    limit = st.selectbox(
        "Rows to display",
        [100, 250, 500],
        index=0,
    )

    log_df = pd.read_sql_query(
        """
        SELECT
            timestamp AS "Date & Time",
            "user" AS "User",
            action AS "Action"
        FROM audit_log
        ORDER BY id DESC
        LIMIT %s
        """,
        conn,
        params=[limit],
    )

    st.dataframe(
        log_df,
        use_container_width=True,
        hide_index=True,
    )

elif page == "Settings":
    require_role("ADMIN")

    page_header(
        "Configuration",
        "Manage global pricing and stock thresholds.",
    )

    render_settings(conn, cursor)

elif page == "Manage Users":
    require_role("ADMIN")

    page_header(
        "User Access",
        "Create accounts and control application permissions.",
    )

    render_user_management(conn, cursor)
