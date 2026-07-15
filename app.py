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
# ---> STEP 1: IMPORT YOUR NEW USER MANAGEMENT FUNCTION
from users_admin import render_user_management

st.set_page_config(page_title="FILLIT", layout="wide")

# ==========================================
# 🔄 PERSISTENCE ENGINE: RESTORE SESSION ON REFRESH
# ==========================================
# If session_state was cleared by a refresh, but URL parameters exist, restore them
if "user" not in st.session_state and "user" in st.query_params:
    st.session_state["user"] = st.query_params["user"]
if "role" not in st.session_state and "role" in st.query_params:
    st.session_state["role"] = st.query_params["role"]

# Connect to Neon
conn = get_connection()
init_db(conn)

# Require user login before loading the rest of the application
require_login(conn)

# Save login states to URL immediately after successful login
if "user" in st.session_state:
    st.query_params["user"] = st.session_state["user"]
if "role" in st.session_state:
    st.query_params["role"] = st.session_state["role"]

st.markdown("<h1 style='text-align:center;color:#c41e3a;'>FILLIT</h1>", unsafe_allow_html=True)
st.markdown(f"Logged in as: {st.session_state['user']} ({st.session_state['role']})")
st.markdown("<hr>", unsafe_allow_html=True)

# ---> STEP 2: DEFINE THE MENU OPTIONS
menu_options = [
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

# Check for uppercase "ADMIN" to match your auth.py role
if st.session_state.get("role") == "ADMIN":
    menu_options.append("👥 Manage Users")

# Determine which page should be selected by default from URL parameters
default_index = 0
if "page" in st.query_params and st.query_params["page"] in menu_options:
    default_index = menu_options.index(st.query_params["page"])

# Render navigation and save choice to URL instantly when clicked
page = st.sidebar.radio("Navigation", menu_options, index=default_index)
st.query_params["page"] = page

# ---> ADD LOG OUT BUTTON TO THE SIDEBAR
st.sidebar.markdown("---")
if st.sidebar.button("🚪 Log Out", use_container_width=True):
    # Clear session state
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    # Clear URL parameters completely on logout
    st.query_params.clear()
    st.rerun()

# Use standard database cursor to query the trucks list
cursor = conn.cursor()
cursor.execute("SELECT id, emirate, plate_code, plate_number FROM trucks")
result = cursor.fetchall()
    
truck_dict = {f"{t[1]} {t[2]} {t[3]}": t[0] for t in result}
truck_list = list(truck_dict.keys())

# ---> STEP 3: ROUTE THE NAVIGATION SELECTIONS
if page == "📊 Dashboard":
    render_dashboard(conn, truck_dict, truck_list)

elif page == "🔄 Transactions":
    render_transactions(conn, cursor, truck_dict, truck_list)

elif page == "🚛 Manage Trucks":
    render_trucks(conn, cursor)

elif page == "📅 Reports":
    render_reports(conn, truck_dict, truck_list)

elif page == "📘 Ledger":
    render_ledger(conn, truck_dict, truck_list)

elif page == "📤 Bulk Delivery Upload":
    render_bulk_upload(conn, cursor, truck_dict, truck_list)

elif page == "✅ Refill Approvals":
    from approvals import render_approvals
    render_approvals(conn, cursor)

elif page == "📜 Audit Log":
    df = pd.read_sql_query("SELECT * FROM audit_log ORDER BY id DESC", conn)
    st.dataframe(df)

elif page == "⚙️ Settings":
    render_settings(conn, cursor)

# Route selection to your new file
elif page == "👥 Manage Users":
    render_user_management(conn, cursor)
