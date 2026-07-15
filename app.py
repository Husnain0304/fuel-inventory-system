import streamlit as st
import pandas as pd
from database import get_connection, init_db
from dashboard import render_dashboard
from transactions import render_transactions
from reports import render_reports
from ledger import render_ledger
from settings import render_settings
from trucks import render_trucks
from bulk_upload import render_bulk_upload
from auth import require_login

st.set_page_config(page_title="FILLIT", layout="wide")

# Connect to Neon PostgreSQL
conn = get_connection()
init_db(conn)

# Require user login before loading the rest of the application
require_login(conn)

st.markdown("<h1 style='text-align:center;color:#c41e3a;'>FILLIT</h1>", unsafe_allow_html=True)
st.markdown(f"Logged in as: {st.session_state['user']} ({st.session_state['role']})")
st.markdown("<hr>", unsafe_allow_html=True)

page = st.sidebar.radio(
    "Navigation",
    [
        "📊 Dashboard",
        "🔄 Transactions",
        "🚛 Manage Trucks",
        "📅 Reports",
        "📘 Ledger",
        "📤 Bulk Delivery Upload",
        "✅ Refill Approvals",
        "📜 Audit Log",
        "⚙️ Settings"
    ]
)

# Extract the raw connection to use cursors
raw_conn = conn.driver_connection

# Use standard cursor to query the trucks list
with raw_conn.cursor() as cursor:
    cursor.execute("SELECT id, emirate, plate_code, plate_number FROM trucks")
    result = cursor.fetchall()
    
truck_dict = {f"{t[1]} {t[2]} {t[3]}": t[0] for t in result}
truck_list = list(truck_dict.keys())

# Create cursor for sub-pages
cursor = raw_conn.cursor()

if page == "📊 Dashboard":
    render_dashboard(raw_conn, truck_dict, truck_list)

elif page == "🔄 Transactions":
    render_transactions(raw_conn, cursor, truck_dict, truck_list)

elif page == "🚛 Manage Trucks":
    render_trucks(raw_conn, cursor)

elif page == "📅 Reports":
    render_reports(raw_conn, truck_dict, truck_list)

elif page == "📘 Ledger":
    render_ledger(raw_conn, truck_dict, truck_list)

elif page == "📤 Bulk Delivery Upload":
    render_bulk_upload(raw_conn, cursor, truck_dict, truck_list)

elif page == "✅ Refill Approvals":
    from approvals import render_approvals
    render_approvals(raw_conn, cursor)

elif page == "📜 Audit Log":
    # Pull audit logs directly using Pandas and the raw connection
    df = pd.read_sql_query("SELECT * FROM audit_log ORDER BY id DESC", raw_conn)
    st.dataframe(df)

elif page == "⚙️ Settings":
    render_settings(raw_conn, cursor)
