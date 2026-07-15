import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime

# Set page configuration
st.set_page_config(page_title="Driver Fuel Log", layout="centered")

# --- CONVERSION FACTOR ---
# 1 Imperial Gallon = 4.54609 Liters
GAL_TO_LITERS = 4.54609

# --- DATABASE CONNECTION ---
def get_connection():
    return psycopg2.connect(st.secrets["postgres"]["url"])

def get_trucks(conn):
    df = pd.read_sql_query("""
        SELECT id, CONCAT(emirate, ' ', plate_code, ' ', plate_number) AS truck 
        FROM trucks 
        ORDER BY plate_number
    """, conn)
    return {row['truck']: row['id'] for _, row in df.iterrows()}

def get_suppliers(conn):
    df = pd.read_sql_query("SELECT id, name FROM suppliers ORDER BY name", conn)
    return {row['name']: row['id'] for _, row in df.iterrows()}

def save_uplift(conn, truck_id, liters, supplier_id, driver_name):
    cursor = conn.cursor()
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    # 1. Insert transaction
    cursor.execute("""
        INSERT INTO transactions (truck_id, date, liters, type, supplier_id, created_by) 
        VALUES (%s, %s, %s, 'IN', %s, %s)
    """, (truck_id, date_str, liters, supplier_id, driver_name))
    
    # 2. Add to audit log
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    action_text = f"Mobile Driver App: Recorded Uplift of {liters:,.2f} L ({liters/GAL_TO_LITERS:,.2f} Imp Gal)"
    cursor.execute(
        'INSERT INTO audit_log ("user", action, timestamp) VALUES (%s, %s, %s)',
        (driver_name, action_text, timestamp)
    )
    
    conn.commit()
    cursor.close()

# --- DRIVER ACCOUNTS ---
DRIVERS = st.secrets.get("drivers", {})

# Initialize session state for login
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.driver_name = ""

# --- REFRESH PERSISTENCE (Query Parameters) ---
query_params = st.query_params
if "user" in query_params and not st.session_state.logged_in:
    saved_user = query_params["user"]
    if saved_user in DRIVERS:
        st.session_state.logged_in = True
        st.session_state.driver_name = DRIVERS[saved_user]["name"]

# Initialize synced conversion states
if "liters_val" not in st.session_state:
    st.session_state.liters_val = 0.0
if "gallons_val" not in st.session_state:
    st.session_state.gallons_val = 0.0

# Initialize submission triggers
if "save_trigger" not in st.session_state:
    st.session_state.save_trigger = False
    st.session_state.pending_liters = 0.0
    st.session_state.pending_gallons = 0.0

# Functions to sync inputs instantly
def update_from_liters():
    st.session_state.gallons_val = round(st.session_state.liters_val / GAL_TO_LITERS, 3)

def update_from_gallons():
    st.session_state.liters_val = round(st.session_state.gallons_val * GAL_TO_LITERS, 3)

# Reset helper
def reset_inputs():
    st.session_state.liters_val = 0.0
    st.session_state.gallons_val = 0.0

# Safe callback to process submit and reset inputs before screen re-renders
def handle_submit_callback():
    if st.session_state.liters_val <= 0:
        st.session_state.submit_error = "⚠️ Please enter a valid fuel quantity!"
    else:
        st.session_state.save_trigger = True
        st.session_state.pending_liters = st.session_state.liters_val
        st.session_state.pending_gallons = st.session_state.gallons_val
        st.session_state.submit_error = None
        # Safely reset values
        reset_inputs()

# --- LOGIN SCREEN ---
if not st.session_state.logged_in:
    st.markdown("<h2 style='text-align: center; color: #008080;'>🔑 Driver Login</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; font-size: 14px; color: gray;'>Enter your driver ID/username and password to start</p>", unsafe_allow_html=True)
    
    username = st.text_input("Username / Driver ID", placeholder="e.g. driver1").strip().lower()
    password = st.text_input("Password", type="password", placeholder="Enter your password")
    
    if st.button("LOG IN", type="primary", use_container_width=True):
        if username in DRIVERS and DRIVERS[username]["password"] == password:
            st.session_state.logged_in = True
            st.session_state.driver_name = DRIVERS[username]["name"]
            st.query_params["user"] = username
            st.rerun()
        else:
            st.error("❌ Incorrect username or password. Please try again.")
    st.stop()

# --- MOBILE APP MAIN SCREEN (LOGGED IN) ---
st.markdown(f"<h2 style='text-align: center; color: #008080;'>🚛 Driver Fuel Entry</h2>", unsafe_allow_html=True)
st.markdown(f"<p style='text-align: center; font-size: 16px; color: #333;'>Welcome back, <b>{st.session_state.driver_name}</b>!</p>", unsafe_allow_html=True)
st.markdown("<hr>", unsafe_allow_html=True)

try:
    conn = get_connection()
    truck_dict = get_trucks(conn)
    supplier_dict = get_suppliers(conn)
    
    # --- PROCESS PENDING DATABASE WRITE ---
    if st.session_state.save_trigger:
        with st.spinner("Saving to system..."):
            save_uplift(
                conn, 
                truck_dict[st.session_state.m_truck], 
                st.session_state.pending_liters, 
                supplier_dict[st.session_state.m_supplier], 
                st.session_state.driver_name
            )
        st.success(f"✅ Uplift of {st.session_state.pending_liters:,.2f} L ({st.session_state.pending_gallons:,.2f} Gal) Recorded Successfully!")
        st.balloons()
        # Clear triggers
        st.session_state.save_trigger = False
    
    if not truck_dict:
        st.warning("No trucks set up in system yet.")
    else:
        selected_truck = st.selectbox("Select Your Truck", list(truck_dict.keys()), key="m_truck")
        selected_supplier = st.selectbox("Select Fuel Supplier", list(supplier_dict.keys()), key="m_supplier")
        
        st.markdown("### ⛽ Enter Quantity")
        
        # Dual-column layout
        col1, col2 = st.columns(2)
        
        with col1:
            liters = st.number_input(
                "Liters (L)", 
                min_value=0.0, 
                step=1.0, 
                key="liters_val", 
                on_change=update_from_liters
            )
            
        with col2:
            gallons = st.number_input(
                "Imperial Gallons (Gal)", 
                min_value=0.0, 
                step=1.0, 
                key="gallons_val", 
                on_change=update_from_gallons
            )
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Display validation error if we tried to submit 0
        if "submit_error" in st.session_state and st.session_state.submit_error:
            st.error(st.session_state.submit_error)
            st.session_state.submit_error = None
        
        # Use on_click callback to safely trigger save and reset
        st.button(
            "🚀 SUBMIT FUEL ENTRY", 
            type="primary", 
            use_container_width=True, 
            on_click=handle_submit_callback
        )
                
    conn.close()
    
except Exception as e:
    st.error(f"Could not connect to database: {e}")

# --- LOGOUT BUTTON AT THE VERY BOTTOM ---
st.markdown("<br><br><br><hr>", unsafe_allow_html=True)
if st.button("🚪 Log Out", use_container_width=True, key="bottom_logout", on_click=reset_inputs):
    st.session_state.logged_in = False
    st.session_state.driver_name = ""
    st.query_params.clear()
    st.rerun()
