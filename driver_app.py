import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime

# Set page configuration to fit perfectly on mobile screens
st.set_page_config(page_title="Driver Fuel Log", layout="centered")

# --- DATABASE CONNECTION ---
# This connects to your Neon Database automatically using your repository secrets
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
    action_text = f"Mobile Driver App: Recorded Uplift of {liters:,.2f} L"
    cursor.execute(
        'INSERT INTO audit_log ("user", action, timestamp) VALUES (%s, %s, %s)',
        (driver_name, action_text, timestamp)
    )
    
    conn.commit()
    cursor.close()

# --- MOBILE UI ---
st.markdown("<h2 style='text-align: center; color: #008080;'>🚛 Driver Fuel Entry</h2>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; font-size: 14px; color: gray;'>Quickly record your fuel uplifts below</p>", unsafe_allow_html=True)

try:
    conn = get_connection()
    truck_dict = get_trucks(conn)
    supplier_dict = get_suppliers(conn)
    
    if not truck_dict:
        st.warning("No trucks set up in system yet.")
    else:
        # Large, easy-to-use form elements for touch screens
        driver_name = st.text_input("Driver Name / ID", placeholder="Enter your name", key="m_driver")
        
        selected_truck = st.selectbox("Select Your Truck", list(truck_dict.keys()), key="m_truck")
        truck_id = truck_dict[selected_truck]
        
        selected_supplier = st.selectbox("Select Fuel Supplier", list(supplier_dict.keys()), key="m_supplier")
        supplier_id = supplier_dict[selected_supplier]
        
        liters = st.number_input("How many liters did you uplift?", min_value=0.0, step=10.0, key="m_liters")
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        if st.button("🚀 SUBMIT FUEL ENTRY", type="primary", use_container_width=True):
            if not driver_name.strip():
                st.error("⚠️ Please enter your name first!")
            elif liters <= 0:
                st.error("⚠️ Please enter a valid number of liters!")
            else:
                with st.spinner("Saving to system..."):
                    save_uplift(conn, truck_id, liters, supplier_id, driver_name.strip())
                st.success("✅ Uplift Recorded Successfully!")
                st.balloons()
                
    conn.close()
    
except Exception as e:
    st.error(f"Could not connect to database: {e}")
