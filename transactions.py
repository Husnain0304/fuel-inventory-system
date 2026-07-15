import streamlit as st
import pandas as pd
from datetime import datetime

# ==========================================
# AUTOMATIC SETUP (PostgreSQL-compatible)
# ==========================================
def auto_setup_db(cursor, conn):
    # 'SERIAL PRIMARY KEY' automatically handles auto-incrementing in PostgreSQL
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id SERIAL PRIMARY KEY,
        "user" TEXT,
        action TEXT,
        timestamp TEXT
    )
    """)
    conn.commit()

# Helper to write to audit log automatically
def log_action(cursor, conn, action_text):
    current_user = st.session_state.get("user", "System Admin")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        'INSERT INTO audit_log ("user", action, timestamp) VALUES (%s, %s, %s)',
        (current_user, action_text, timestamp)
    )
    conn.commit()

def get_balance(conn, truck_id):
    # PostgreSQL uses %s as the parameter placeholder
    df = pd.read_sql_query("""
        SELECT 
            SUM(CASE WHEN type='IN' THEN liters ELSE 0 END) -
            SUM(CASE WHEN type='OUT' THEN liters ELSE 0 END)
        FROM transactions
        WHERE truck_id = %s
    """, conn, params=[truck_id])
    return df.iloc[0, 0] or 0

# ==========================================
# MAIN TRANSACTIONS INTERFACE
# ==========================================
def render_transactions(conn, cursor, truck_dict, truck_list):
    # Run the database auto-setup quietly in the background
    auto_setup_db(cursor, conn)

    # Temporary fallback: If you haven't logged in, we temporarily give you access
    if "role" not in st.session_state:
        st.session_state["role"] = "ADMIN"
    if "user" not in st.session_state:
        st.session_state["user"] = "Admin_User"

    st.title("🔄 Transactions")

    if not truck_list:
        st.warning("Add a truck first.")
        return

    # Tabs make switching between actions and viewing logs extremely easy
    tab1, tab2, tab3 = st.tabs(["➕ Add Entry", "📜 View & Delete History", "📋 View Audit Logs"])

    # =============================
    # TAB 1: ADD ENTRY (UPLIFT / DELIVERY)
    # =============================
    with tab1:
        mode = st.radio("Select Action Type", ["UPLIFT (Fuel IN)", "DELIVERY (Fuel OUT)"], horizontal=True)
        truck = st.selectbox("Select Truck", truck_list, key="add_tx_truck")
        truck_id = truck_dict[truck]

        balance = get_balance(conn, truck_id)
        st.info(f"Current Balance: {balance:,.2f} L")

        date = st.date_input("Date", key="tx_date")
        liters = st.number_input("Liters", min_value=0.0, key="tx_liters")

        if mode == "UPLIFT (Fuel IN)":
            if st.button("Save Uplift Entry", type="primary"):
                cursor.execute(
                    "INSERT INTO transactions (truck_id,date,liters,type) VALUES (%s,%s,%s,'IN')",
                    (truck_id, str(date), liters)
                )
                log_action(cursor, conn, f"Added Uplift of {liters:,.2f} L for Truck '{truck}' on date {date}")
                st.success("Uplift recorded successfully! ✅")
                st.rerun()

        elif mode == "DELIVERY (Fuel OUT)":
            if st.button("Save Delivery Entry", type="primary"):
                if liters > balance:
                    st.error("❌ Insufficient balance in this truck!")
                else:
                    cursor.execute(
                        "INSERT INTO transactions (truck_id,date,liters,type) VALUES (%s,%s,%s,'OUT')",
                        (truck_id, str(date), liters)
                    )
                    log_action(cursor, conn, f"Added Delivery of {liters:,.2f} L for Truck '{truck}' on date {date}")
                    st.success("Delivery recorded successfully! ✅")
                    st.rerun()

    # =============================
    # TAB 2: HISTORY (CHECKBOXES & GROUP VIEWS)
    # =============================
    with tab2:
        # Replaced SQLite "||" with PostgreSQL "CONCAT" syntax
        history_df = pd.read_sql_query("""
            SELECT transactions.id AS id,
                   transactions.date,
                   transactions.truck_id,
                   CONCAT(trucks.emirate, ' ', trucks.plate_code, ' ', trucks.plate_number) AS truck,
                   transactions.liters,
                   transactions.type
            FROM transactions
            JOIN trucks ON transactions.truck_id = trucks.id
            ORDER BY transactions.id DESC
        """, conn)

        if history_df.empty:
            st.info("No transactions recorded yet.")
        else:
            history_df['date_parsed'] = pd.to_datetime(history_df['date'])

            # Initialize tracking for checkboxes
            if "selected_tx_ids" not in st.session_state:
                st.session_state["selected_tx_ids"] = set()

            # --- Filter section ---
            with st.expander("🔍 Filter History Table"):
                col_f1, col_f2 = st.columns(2)
                min_date = history_df['date_parsed'].min().date()
                max_date = history_df['date_parsed'].max().date()
                selected_dates = col_f1.date_input("Date Range", value=(min_date, max_date))
                
                selected_trucks = col_f2.multiselect("Select Trucks", options=list(history_df['truck'].unique()))
                
                type_filter = st.selectbox("Transaction Type", ["All", "IN (Uplift)", "OUT (Delivery)"])

            # Filter data
            filtered_df = history_df.copy()
            if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
                filtered_df = filtered_df[
                    (filtered_df['date_parsed'].dt.date >= selected_dates[0]) & 
                    (filtered_df['date_parsed'].dt.date <= selected_dates[1])
                ]
            if selected_trucks:
                filtered_df = filtered_df[filtered_df['truck'].isin(selected_trucks)]
            if type_filter == "IN (Uplift)":
                filtered_df = filtered_df[filtered_df['type'] == 'IN']
            elif type_filter == "OUT (Delivery)":
                filtered_df = filtered_df[filtered_df['type'] == 'OUT']

            # --- BULK DELETE WORKSPACE ---
            selected_count = len(st.session_state["selected_tx_ids"])
            if selected_count > 0:
                st.warning(f"⚠️ You have selected **{selected_count}** transaction entries.")
                confirm_bulk = st.checkbox("Check here to confirm you want to delete these selected records.")
                
                if st.button("🗑️ Delete Selected Rows permanently", type="primary"):
                    if confirm_bulk:
                        id_list = list(st.session_state["selected_tx_ids"])
                        # PostgreSQL parameter placeholder mapping
                        placeholders = ",".join("%s" for _ in id_list)
                        
                        # Grab details before deleting for the log (Using PostgreSQL CONCAT)
                        log_df = pd.read_sql_query(f"""
                            SELECT transactions.id, transactions.date, transactions.liters, transactions.type,
                                   CONCAT(trucks.emirate, ' ', trucks.plate_code, ' ', trucks.plate_number) AS truck
                            FROM transactions
                            JOIN trucks ON transactions.truck_id = trucks.id
                            WHERE transactions.id IN ({placeholders})
                        """, conn, params=id_list)
                        
                        # Execute Delete
                        cursor.execute(f"DELETE FROM transactions WHERE id IN ({placeholders})", id_list)
                        
                        # Write details to log
                        for _, row in log_df.iterrows():
                            log_action(cursor, conn, f"DELETED Record: ID {row['id']} ({row['liters']:,.2f} L, type: {row['type']}) for Truck '{row['truck']}' on date {row['date']}")
                        
                        conn.commit()
                        st.session_state["selected_tx_ids"] = set() # Reset checkbox list
                        st.success(f"Successfully deleted {selected_count} entries!")
                        st.rerun()
                    else:
                        st.error("Please check the confirmation checkbox first!")

            st.markdown("---")

            # --- Group display ---
            grouped_df = (
                filtered_df.groupby(["date", "truck", "truck_id", "type"])["liters"]
                .sum()
                .reset_index()
            ).sort_values(by="date", ascending=False)

            col_h0, col_h1, col_h2, col_h3, col_h4, col_h5 = st.columns([1, 2, 3, 2, 2, 2])
            col_h0.markdown("**Select**")
            col_h1.markdown("**Date**")
            col_h2.markdown("**Truck**")
            col_h3.markdown("**Total Liters**")
            col_h4.markdown("**Type**")
            col_h5.markdown("**Details**")
            st.markdown("---")

            for idx, row in grouped_df.iterrows():
                group_key = f"{row['date']}_{row['truck_id']}_{row['type']}_{idx}"
                
                # Retrieve individual records for this specific summary row
                child_records = filtered_df[
                    (filtered_df['date'] == row['date']) & 
                    (filtered_df['truck_id'] == row['truck_id']) & 
                    (filtered_df['type'] == row['type'])
                ]
                child_ids = set(child_records['id'].tolist())

                col0, col1, col2, col3, col4, col5 = st.columns([1, 2, 3, 2, 2, 2])

                # Checkbox to select all entries in this group at once
                group_checked = child_ids.issubset(st.session_state["selected_tx_ids"])
                select_group = col0.checkbox("", value=group_checked, key=f"chk_grp_{group_key}")

                if select_group and not group_checked:
                    st.session_state["selected_tx_ids"].update(child_ids)
                    st.rerun()
                elif not select_group and group_checked:
                    st.session_state["selected_tx_ids"].difference_update(child_ids)
                    st.rerun()

                col1.write(row["date"])
                col2.write(row["truck"])
                col3.write(f"{row['liters']:,.2f} L")
                
                if row["type"] == "IN":
                    col4.markdown("<span style='color:green;font-weight:bold;'>IN (Uplift)</span>", unsafe_allow_html=True)
                else:
                    col4.markdown("<span style='color:orange;font-weight:bold;'>OUT (Delivery)</span>", unsafe_allow_html=True)

                # Drill-down detailed items toggler
                expander_state_key = f"exp_{group_key}"
                if col5.button("🔍 Details", key=f"btn_details_{group_key}", use_container_width=True):
                    st.session_state[expander_state_key] = not st.session_state.get(expander_state_key, False)
                    st.rerun()

                # Detailed items expander drawer
                if st.session_state.get(expander_state_key, False):
                    with st.container(border=True):
                        st.markdown(f"**🔎 Individual Items making up this {row['liters']:,.2f} L sum:**")
                        for _, item in child_records.iterrows():
                            d_col0, d_col1, d_col2, d_col3 = st.columns([1, 4, 3, 2])
                            
                            # Single checkbox inside detail drawer
                            item_checked = item['id'] in st.session_state["selected_tx_ids"]
                            select_item = d_col0.checkbox("", value=item_checked, key=f"chk_indiv_{item['id']}")
                            
                            if select_item and not item_checked:
                                st.session_state["selected_tx_ids"].add(item['id'])
                                st.rerun()
                            elif not select_item and item_checked:
                                st.session_state["selected_tx_ids"].remove(item['id'])
                                st.rerun()

                            d_col1.write(f"Record System ID: {item['id']}")
                            d_col2.write(f"{item['liters']:,.2f} L")
                            
                            # Quick Edit trigger
                            if d_col3.button("✏️ Edit", key=f"btn_edit_{item['id']}", use_container_width=True):
                                st.session_state["active_edit_id"] = item["id"]
                                st.rerun()

    # =============================
    # TAB 3: SYSTEM AUDIT LOG VIEWER
    # =============================
    with tab3:
        st.subheader("📋 Complete System Activity History")
        st.markdown("This tab automatically logs every action, telling you who performed a change, what change they made, and when it happened.")
        
        # PostgreSQL-compatible SQL syntax for column headers with spaces
        logs_df = pd.read_sql_query("""
            SELECT timestamp AS "Date & Time", 
                   "user" AS "User", 
                   action AS "Action" 
            FROM audit_log 
            ORDER BY id DESC
        """, conn)
        
        if logs_df.empty:
            st.info("No actions logged in the system database yet.")
        else:
            search = st.text_input("🔍 Search logs (type usernames, actions, dates, plate codes, etc.)", "")
            if search:
                logs_df = logs_df[
                    logs_df['User'].str.contains(search, case=False, na=False) |
                    logs_df['Action'].str.contains(search, case=False, na=False)
                ]
            st.dataframe(logs_df, use_container_width=True, hide_index=True)


    # ==========================================
    # POPUP INLINE EDIT MODE (Appears below when ✏️ is clicked)
    # ==========================================
    if "active_edit_id" in st.session_state:
        edit_id = st.session_state["active_edit_id"]
        tx_data = pd.read_sql_query("SELECT * FROM transactions WHERE id=%s", conn, params=[edit_id])

        if not tx_data.empty:
            st.markdown("---")
            st.subheader(f"✏️ Modify Entry ID: {edit_id}")
            
            orig_date = pd.to_datetime(tx_data.iloc[0]["date"])
            orig_liters = tx_data.iloc[0]["liters"]
            orig_type = tx_data.iloc[0]["type"]
            t_id = tx_data.iloc[0]["truck_id"]

            new_date = st.date_input("Change Date", value=orig_date, key="edit_val_date")
            new_liters = st.number_input("Change Liters", value=float(orig_liters), key="edit_val_liters")
            new_type = st.selectbox("Change Type", ["IN", "OUT"], index=0 if orig_type == "IN" else 1, key="edit_val_type")

            confirm_change = st.checkbox("I verify that I want to edit this database record and understand it updates inventory math.")

            col_btn1, col_btn2 = st.columns(2)
            
            if col_btn1.button("Save Updates", type="primary"):
                if not confirm_change:
                    st.error("Please check the confirmation box to authorize edit!")
                else:
                    cursor.execute("""
                        UPDATE transactions SET date=%s, liters=%s, type=%s WHERE id=%s
                    """, (str(new_date), new_liters, new_type, edit_id))
                    
                    # Audit Log
                    log_action(cursor, conn, f"EDITED Entry ID {edit_id}: Changed Date ({orig_date.date()} -> {new_date}), Liters ({orig_liters} -> {new_liters}), Type ({orig_type} -> {new_type})")
                    
                    conn.commit()
                    st.success("Record updated successfully!")
                    del st.session_state["active_edit_id"]
                    st.rerun()

            if col_btn2.button("Cancel Changes"):
                del st.session_state["active_edit_id"]
                st.rerun()
