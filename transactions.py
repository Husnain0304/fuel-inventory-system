import streamlit as st
import pandas as pd
from datetime import datetime

def auto_setup_db(cursor, conn):
    # 1. Ensure audit_log table exists
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id SERIAL PRIMARY KEY,
        "user" TEXT,
        action TEXT,
        timestamp TEXT
    )
    """)
    
    # 2. Ensure suppliers table exists
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS suppliers (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE NOT NULL
    )
    """)
    
    # 3. Ensure a default supplier exists so the application doesn't break
    cursor.execute("INSERT INTO suppliers (name) VALUES ('Default Supplier') ON CONFLICT (name) DO NOTHING")
    
    # 4. Safely add missing columns to the transactions table if they don't exist
    cursor.execute("""
    ALTER TABLE transactions ADD COLUMN IF NOT EXISTS supplier_id INTEGER REFERENCES suppliers(id);
    """)
    cursor.execute("""
    ALTER TABLE transactions ADD COLUMN IF NOT EXISTS transfer_partner_id INTEGER;
    """)
    cursor.execute("""
    ALTER TABLE transactions ADD COLUMN IF NOT EXISTS created_by TEXT;
    """)
    
    conn.commit()

def log_action(cursor, conn, action_text):
    current_user = st.session_state.get("user", "System Admin")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        'INSERT INTO audit_log ("user", action, timestamp) VALUES (%s, %s, %s)',
        (current_user, action_text, timestamp)
    )
    conn.commit()

def get_balance(conn, truck_id):
    df = pd.read_sql_query("""
        SELECT 
            SUM(CASE WHEN type='IN' THEN liters ELSE 0 END) -
            SUM(CASE WHEN type='OUT' THEN liters ELSE 0 END)
        FROM transactions
        WHERE truck_id = %s
    """, conn, params=[truck_id])
    return df.iloc[0, 0] or 0

def render_transactions(conn, cursor, truck_dict, truck_list):
    # Setup tables and columns first to prevent Pandas query errors
    auto_setup_db(cursor, conn)

    if "role" not in st.session_state:
        st.session_state["role"] = "ADMIN"
    if "user" not in st.session_state:
        st.session_state["user"] = "Admin_User"

    st.title("🔄 Transactions & Logistics")

    if not truck_list:
        st.warning("Add a truck first.")
        return

    # Fetch current suppliers from DB
    suppliers_df = pd.read_sql_query("SELECT id, name FROM suppliers ORDER BY name", conn)
    supplier_dict = {row['name']: row['id'] for _, row in suppliers_df.iterrows()}
    supplier_list = list(supplier_dict.keys())

    # App Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "➕ Add Entry", 
        "🚛 Truck Transfer", 
        "🏢 Manage Suppliers", 
        "📜 View & Filter History", 
        "📋 View Audit Logs"
    ])

    # Get active user info
    active_user = st.session_state.get("user", "Admin_User")

    # ==========================================
    # TAB 1: ADD ENTRY (UPLIFT / DELIVERY)
    # ==========================================
    with tab1:
        mode = st.radio("Select Action Type", ["UPLIFT (Fuel IN)", "DELIVERY (Fuel OUT)"], horizontal=True)
        truck = st.selectbox("Select Truck", truck_list, key="add_tx_truck")
        truck_id = truck_dict[truck]

        balance = get_balance(conn, truck_id)
        st.info(f"Current Balance: {balance:,.2f} L")

        date = st.date_input("Date", key="tx_date")
        liters = st.number_input("Liters", min_value=0.0, key="tx_liters")

        if mode == "UPLIFT (Fuel IN)":
            selected_supplier_name = st.selectbox("Select Supplier", supplier_list if supplier_list else ["Default Supplier"])
            supplier_id = supplier_dict.get(selected_supplier_name, None)

            if st.button("Save Uplift Entry", type="primary"):
                if liters <= 0:
                    st.error("Please enter a valid amount of liters.")
                else:
                    cursor.execute("""
                        INSERT INTO transactions (truck_id, date, liters, type, supplier_id, created_by) 
                        VALUES (%s, %s, %s, 'IN', %s, %s)
                    """, (truck_id, str(date), liters, supplier_id, active_user))
                    conn.commit()
                    log_action(cursor, conn, f"Added Uplift of {liters:,.2f} L from Supplier '{selected_supplier_name}' for Truck '{truck}' on date {date}")
                    st.success("Uplift recorded successfully! ✅")
                    st.rerun()

        elif mode == "DELIVERY (Fuel OUT)":
            if st.button("Save Delivery Entry", type="primary"):
                if liters <= 0:
                    st.error("Please enter a valid amount of liters.")
                elif liters > balance:
                    st.error("❌ Insufficient balance in this truck!")
                else:
                    cursor.execute("""
                        INSERT INTO transactions (truck_id, date, liters, type, created_by) 
                        VALUES (%s, %s, %s, 'OUT', %s)
                    """, (truck_id, str(date), liters, active_user))
                    conn.commit()
                    log_action(cursor, conn, f"Added Delivery of {liters:,.2f} L for Truck '{truck}' on date {date}")
                    st.success("Delivery recorded successfully! ✅")
                    st.rerun()

    # ==========================================
    # TAB 2: TRUCK TO TRUCK TRANSFER
    # ==========================================
    with tab2:
        st.subheader("Direct Fuel Transfer")
        col_t1, col_t2 = st.columns(2)
        
        source_truck = col_t1.selectbox("From Truck (Source)", truck_list, key="transfer_source")
        
        # Filter out the source truck so a truck can't transfer to itself
        available_dest_trucks = [t for t in truck_list if t != source_truck]
        
        if not available_dest_trucks:
            col_t2.warning("Add more trucks to enable transfers.")
            dest_truck = None
        else:
            dest_truck = col_t2.selectbox("To Truck (Destination)", available_dest_trucks, key="transfer_dest")

        # Safely acquire IDs only if we have a valid destination choice
        source_id = truck_dict[source_truck]
        source_balance = get_balance(conn, source_id)
        col_t1.info(f"Source Balance: {source_balance:,.2f} L")
        
        if dest_truck:
            dest_id = truck_dict[dest_truck]
            dest_balance = get_balance(conn, dest_id)
            col_t2.info(f"Destination Balance: {dest_balance:,.2f} L")
        else:
            dest_id = None
            col_t2.info("Destination Balance: 0.00 L")

        transfer_date = st.date_input("Transfer Date", key="transfer_date")
        transfer_liters = st.number_input("Transfer Liters", min_value=0.0, key="transfer_liters")

        if st.button("Confirm Fuel Transfer", type="primary"):
            if not dest_truck:
                st.error("❌ Cannot transfer fuel without a valid destination truck.")
            elif transfer_liters <= 0:
                st.error("Please enter liters to transfer.")
            elif transfer_liters > source_balance:
                st.error("❌ Source truck does not have enough inventory!")
            else:
                try:
                    cursor.execute("""
                        INSERT INTO transactions (truck_id, date, liters, type, created_by) 
                        VALUES (%s, %s, %s, 'OUT', %s) RETURNING id
                    """, (source_id, str(transfer_date), transfer_liters, active_user))
                    source_tx_id = cursor.fetchone()[0]

                    cursor.execute("""
                        INSERT INTO transactions (truck_id, date, liters, type, created_by) 
                        VALUES (%s, %s, %s, 'IN', %s) RETURNING id
                    """, (dest_id, str(transfer_date), transfer_liters, active_user))
                    dest_tx_id = cursor.fetchone()[0]

                    cursor.execute("UPDATE transactions SET transfer_partner_id = %s WHERE id = %s", (dest_tx_id, source_tx_id))
                    cursor.execute("UPDATE transactions SET transfer_partner_id = %s WHERE id = %s", (source_tx_id, dest_tx_id))
                    
                    conn.commit()
                    log_action(cursor, conn, f"TRANSFERRED {transfer_liters:,.2f} L from '{source_truck}' to '{dest_truck}'")
                    st.success(f"Successfully transferred {transfer_liters:,.2f} L! 🚛💨")
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"Error executing transfer: {e}")

    # ==========================================
    # TAB 3: MANAGE SUPPLIERS
    # ==========================================
    with tab3:
        st.subheader("Manage Suppliers")
        with st.form("add_supplier_form", clear_on_submit=True):
            new_supplier = st.text_input("New Supplier Name").strip()
            if st.form_submit_button("Add Supplier"):
                if new_supplier:
                    try:
                        cursor.execute("INSERT INTO suppliers (name) VALUES (%s)", (new_supplier,))
                        conn.commit()
                        st.success(f"Supplier '{new_supplier}' added!")
                        st.rerun()
                    except Exception:
                        conn.rollback()
                        st.error("This supplier is already registered.")

    # ==========================================
    # TAB 4: VIEW & FILTER HISTORY (POWER FILTERED)
    # ==========================================
    with tab4:
        st.subheader("🧐 Historical Audit & Filter Engine")

        # Fetch entire history join with created_by field included
        history_df = pd.read_sql_query("""
            SELECT transactions.id AS id,
                   transactions.date,
                   transactions.truck_id,
                   CONCAT(trucks.emirate, ' ', trucks.plate_code, ' ', trucks.plate_number) AS truck,
                   transactions.liters,
                   transactions.type,
                   suppliers.name AS supplier_name,
                   transactions.transfer_partner_id,
                   COALESCE(transactions.created_by, 'System') AS created_by
            FROM transactions
            JOIN trucks ON transactions.truck_id = trucks.id
            LEFT JOIN suppliers ON transactions.supplier_id = suppliers.id
            ORDER BY transactions.id DESC
        """, conn)

        if history_df.empty:
            st.info("No transaction data found in database.")
        else:
            history_df['date_parsed'] = pd.to_datetime(history_df['date'])

            # --- ADVANCED FILTER INTERFACE ---
            with st.container(border=True):
                st.markdown("⚡ **Filter Controls**")
                col_f1, col_f2 = st.columns(2)
                
                # 1. Date Filter
                min_date = history_df['date_parsed'].min().date()
                max_date = history_df['date_parsed'].max().date()
                selected_dates = col_f1.date_input("Filter by Date Range", value=(min_date, max_date))
                
                # 2. Truck Filter
                selected_trucks = col_f2.multiselect("Filter by Truck Number", options=list(history_df['truck'].unique()))
                
                col_f3, col_f4 = st.columns(2)
                
                # 3. Transaction Type Filter
                type_filter = col_f3.selectbox(
                    "Filter by Transaction Name/Type", 
                    ["All Transactions", "Standard Uplift (IN)", "Standard Delivery (OUT)", "Internal Transfers Only"]
                )
                
                # 4. Global Text Search
                search_query = col_f4.text_input("Global Search (Supplier name, ID, User, etc.)", "").strip().lower()

            # --- APPLY FILTER LOGIC ---
            filtered_df = history_df.copy()

            # Date check
            if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
                filtered_df = filtered_df[
                    (filtered_df['date_parsed'].dt.date >= selected_dates[0]) & 
                    (filtered_df['date_parsed'].dt.date <= selected_dates[1])
                ]
            
            # Truck check
            if selected_trucks:
                filtered_df = filtered_df[filtered_df['truck'].isin(selected_trucks)]
            
            # Type check
            if type_filter == "Standard Uplift (IN)":
                filtered_df = filtered_df[(filtered_df['type'] == 'IN') & (filtered_df['transfer_partner_id'].isna())]
            elif type_filter == "Standard Delivery (OUT)":
                filtered_df = filtered_df[(filtered_df['type'] == 'OUT') & (filtered_df['transfer_partner_id'].isna())]
            elif type_filter == "Internal Transfers Only":
                filtered_df = filtered_df[filtered_df['transfer_partner_id'].notna()]

            # Text string query matching
            if search_query:
                filtered_df = filtered_df[
                    (filtered_df['supplier_name'].str.lower().str.contains(search_query, na=False)) |
                    (filtered_df['truck'].str.lower().str.contains(search_query, na=False)) |
                    (filtered_df['created_by'].str.lower().str.contains(search_query, na=False)) |
                    (filtered_df['id'].astype(str).str.contains(search_query))
                ]

            # Display Data Metric metrics
            st.markdown(f"Showing **{len(filtered_df)}** matching transaction actions:")

            # Render Table Headers
            col_h1, col_h2, col_h3, col_h4, col_h5, col_h6 = st.columns([2, 3, 2, 3, 2, 2])
            col_h1.markdown("**Date**")
            col_h2.markdown("**Truck Reference**")
            col_h3.markdown("**Quantity**")
            col_h4.markdown("**Transaction Context**")
            col_h5.markdown("**Recorded By**")
            col_h6.markdown("**Record ID**")
            st.markdown("---")

            # Render Filtered Rows
            for _, item in filtered_df.iterrows():
                col1, col2, col3, col4, col5, col6 = st.columns([2, 3, 2, 3, 2, 2])
                col1.write(item["date"])
                col2.write(f"🚛 {item['truck']}")
                col3.write(f"**{item['liters']:,.2f} L**")
                
                # Context badge rendering
                if item['transfer_partner_id']:
                    ctx = f"🔄 Transfer ({'Into Truck' if item['type']=='IN' else 'Out of Truck'})"
                else:
                    ctx = f"📥 Uplift [Supplier: {item['supplier_name']}]" if item['type'] == 'IN' else "📤 Regular Delivery"
                
                col4.write(ctx)
                col5.write(f"👤 {item['created_by']}")
                col6.write(f"`TX-{item['id']}`")

    # ==========================================
    # TAB 5: SYSTEM AUDIT LOG VIEWER
    # ==========================================
    with tab5:
        st.subheader("📋 Complete System Activity History")
        logs_df = pd.read_sql_query('SELECT timestamp AS "Date & Time", "user" AS "User", action AS "Action" FROM audit_log ORDER BY id DESC', conn)
        if logs_df.empty:
            st.info("No actions logged.")
        else:
            st.dataframe(logs_df, use_container_width=True, hide_index=True)
