import streamlit as st
import pandas as pd
from datetime import datetime
import io  # Required for in-memory Excel file generation

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
    
    # 3. Ensure a default supplier exists
    cursor.execute("INSERT INTO suppliers (name) VALUES ('Default Supplier') ON CONFLICT (name) DO NOTHING")
    
    # 4. Safely add missing columns
    cursor.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS supplier_id INTEGER REFERENCES suppliers(id);")
    cursor.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS transfer_partner_id INTEGER;")
    cursor.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS created_by TEXT;")
    
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

@st.dialog("✏️ Edit Transaction")
def edit_transaction_dialog(conn, cursor, tx_item, supplier_dict):
    st.write(f"Editing Transaction **TX-{tx_item['id']}** for Truck **{tx_item['truck']}**")
    
    new_date = st.date_input("Date", value=pd.to_datetime(tx_item['date']).date())
    new_liters = st.number_input("Liters", min_value=0.1, value=float(tx_item['liters']))
    
    supplier_list = list(supplier_dict.keys())
    current_supplier = tx_item['supplier_name'] if tx_item['supplier_name'] in supplier_list else (supplier_list[0] if supplier_list else None)
    
    if tx_item['type'] == 'IN' and not tx_item['transfer_partner_id']:
        new_supplier = st.selectbox("Supplier", supplier_list, index=supplier_list.index(current_supplier) if current_supplier in supplier_list else 0)
        new_supplier_id = supplier_dict.get(new_supplier)
    else:
        new_supplier_id = tx_item.get('supplier_id')

    if st.button("Save Changes", type="primary"):
        cursor.execute("""
            UPDATE transactions 
            SET date = %s, liters = %s, supplier_id = %s
            WHERE id = %s
        """, (str(new_date), new_liters, new_supplier_id, tx_item['id']))
        
        # Update partner transaction if part of a transfer
        if tx_item['transfer_partner_id']:
            cursor.execute("UPDATE transactions SET liters = %s, date = %s WHERE id = %s", 
                           (new_liters, str(new_date), tx_item['transfer_partner_id']))

        conn.commit()
        log_action(cursor, conn, f"EDITED TX-{tx_item['id']}: Updated Liters to {new_liters:,.2f} L and Date to {new_date}")
        st.success("Transaction updated!")
        st.rerun()

@st.dialog("⚠️ Confirm Bulk Delete")
def confirm_bulk_delete_dialog(conn, cursor, truck_id, truck_name, start_date, end_date, supplier_id=None):
    st.warning(f"Are you sure you want to delete transactions for **{truck_name}** between **{start_date}** and **{end_date}**?")
    
    if supplier_id:
        cursor.execute("""
            SELECT COUNT(*) FROM transactions 
            WHERE truck_id = %s AND date >= %s AND date <= %s AND supplier_id = %s
        """, (truck_id, str(start_date), str(end_date), supplier_id))
    else:
        cursor.execute("""
            SELECT COUNT(*) FROM transactions 
            WHERE truck_id = %s AND date >= %s AND date <= %s
        """, (truck_id, str(start_date), str(end_date)))
    
    count = cursor.fetchone()[0]
    st.write(f"📊 **Total records to be deleted:** `{count}`")

    if count == 0:
        st.info("No matching records found for this selection.")
        return

    if st.button("🔴 YES, DELETE THESE RECORDS", type="primary", use_container_width=True):
        if supplier_id:
            cursor.execute("""
                DELETE FROM transactions 
                WHERE truck_id = %s AND date >= %s AND date <= %s AND supplier_id = %s
            """, (truck_id, str(start_date), str(end_date), supplier_id))
        else:
            cursor.execute("""
                DELETE FROM transactions 
                WHERE truck_id = %s AND date >= %s AND date <= %s
            """, (truck_id, str(start_date), str(end_date)))
        
        conn.commit()
        log_action(cursor, conn, f"BULK DELETED {count} transactions for Truck '{truck_name}' between {start_date} and {end_date}")
        st.success(f"Successfully deleted {count} records! You can now re-upload your corrected file.")
        st.rerun()

# ==========================================
# NEW ADMIN-ONLY CLEAR DATA DIALOGS
# ==========================================
@st.dialog("⚠️ CONFIRM CLEAR ALL IN (UPLIFT) DATA")
def confirm_clear_in_dialog(conn, cursor):
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE type = 'IN'")
    count = cursor.fetchone()[0]
    
    st.error(f"🚨 **WARNING:** You are about to permanently delete ALL **{count}** UPLIFT (Fuel IN) records from the database!")
    st.write("This action cannot be undone.")

    if count == 0:
        st.info("No UPLIFT (IN) records found to delete.")
        return

    if st.button("🔴 YES, WIPE ALL IN / UPLIFT RECORDS", type="primary", use_container_width=True):
        cursor.execute("DELETE FROM transactions WHERE type = 'IN'")
        conn.commit()
        log_action(cursor, conn, f"ADMIN WIPED ALL UPLIFT (IN) TRANSACTIONS ({count} records)")
        st.success(f"Successfully deleted all {count} IN (Uplift) records!")
        st.rerun()

@st.dialog("⚠️ CONFIRM CLEAR ALL OUT (DELIVERY) DATA")
def confirm_clear_out_dialog(conn, cursor):
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE type = 'OUT'")
    count = cursor.fetchone()[0]
    
    st.error(f"🚨 **WARNING:** You are about to permanently delete ALL **{count}** DELIVERY (Fuel OUT) records from the database!")
    st.write("This action cannot be undone.")

    if count == 0:
        st.info("No DELIVERY (OUT) records found to delete.")
        return

    if st.button("🔴 YES, WIPE ALL OUT / DELIVERY RECORDS", type="primary", use_container_width=True):
        cursor.execute("DELETE FROM transactions WHERE type = 'OUT'")
        conn.commit()
        log_action(cursor, conn, f"ADMIN WIPED ALL DELIVERY (OUT) TRANSACTIONS ({count} records)")
        st.success(f"Successfully deleted all {count} OUT (Delivery) records!")
        st.rerun()


def render_transactions(conn, cursor, truck_dict, truck_list):
    auto_setup_db(cursor, conn)

    if "role" not in st.session_state:
        st.session_state["role"] = "ADMIN"
    if "user" not in st.session_state:
        st.session_state["user"] = "Admin_User"

    st.title("🔄 Transactions & Logistics")

    if not truck_list:
        st.warning("Add a truck first.")
        return

    suppliers_df = pd.read_sql_query("SELECT id, name FROM suppliers ORDER BY name", conn)
    supplier_dict = {row['name']: row['id'] for _, row in suppliers_df.iterrows()}
    supplier_list = list(supplier_dict.keys())

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "➕ Add Entry", 
        "🚛 Truck Transfer", 
        "🏢 Manage Suppliers", 
        "📜 View & Filter History", 
        "📋 View Audit Logs"
    ])

    active_user = st.session_state.get("user", "Admin_User")
    user_role = st.session_state.get("role", "USER")

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
        available_dest_trucks = [t for t in truck_list if t != source_truck]
        
        if not available_dest_trucks:
            col_t2.warning("Add more trucks to enable transfers.")
            dest_truck = None
        else:
            dest_truck = col_t2.selectbox("To Truck (Destination)", available_dest_trucks, key="transfer_dest")

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
    # TAB 4: VIEW, SUMMARY, EDIT & BULK DELETE
    # ==========================================
    with tab4:
        st.subheader("🧐 Historical Audit & Filter Engine")

        # --- ADMIN WIPE DATA SECTION ---
        if user_role == "ADMIN":
            with st.expander("🔑 Admin Database Purge Controls", expanded=False):
                st.warning("⚠️ **ADMIN ONLY ZONE:** Clearing transaction types will purge corresponding records across all trucks.")
                col_clear_in, col_clear_out = st.columns(2)
                
                if col_clear_in.button("🔥 Clear ALL UPLIFT (IN) Data", use_container_width=True):
                    confirm_clear_in_dialog(conn, cursor)
                
                if col_clear_out.button("🔥 Clear ALL DELIVERY (OUT) Data", use_container_width=True):
                    confirm_clear_out_dialog(conn, cursor)

        history_df = pd.read_sql_query("""
            SELECT transactions.id AS id,
                   transactions.date,
                   transactions.truck_id,
                   CONCAT(trucks.emirate, ' ', trucks.plate_code, ' ', trucks.plate_number) AS truck,
                   transactions.liters,
                   transactions.type,
                   suppliers.name AS supplier_name,
                   transactions.supplier_id,
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

            view_mode = st.radio(
                "Select View Mode", 
                ["📊 Summarized Fleet Totals", "📜 Detailed Transaction Records", "🚨 Bulk Delete Operations"], 
                horizontal=True
            )

            # 1. SUMMARIZED TOTALS BY TRUCK
            if view_mode == "📊 Summarized Fleet Totals":
                st.markdown("### 🚛 Total Fuel Summary by Truck")
                
                summary_df = history_df.groupby('truck').apply(
                    lambda g: pd.Series({
                        'Total Uplift / IN (L)': g[g['type'] == 'IN']['liters'].sum(),
                        'Total Delivery / OUT (L)': g[g['type'] == 'OUT']['liters'].sum(),
                        'Net Balance (L)': g[g['type'] == 'IN']['liters'].sum() - g[g['type'] == 'OUT']['liters'].sum(),
                        'Total Transactions': len(g)
                    })
                ).reset_index()

                st.dataframe(
                    summary_df.style.format({
                        'Total Uplift / IN (L)': '{:,.2f}',
                        'Total Delivery / OUT (L)': '{:,.2f}',
                        'Net Balance (L)': '{:,.2f}',
                        'Total Transactions': '{:,.0f}'
                    }),
                    use_container_width=True,
                    hide_index=True
                )

            # 2. BULK DELETE TOOL (DATE RANGE & TRUCK)
            elif view_mode == "🚨 Bulk Delete Operations":
                st.markdown("### 🗑️ Bulk Delete Uploaded Data")
                st.warning("Use this panel to erase wrong batch uploads for a truck and date range before re-uploading your clean file.")

                col_b1, col_b2 = st.columns(2)
                target_truck = col_b1.selectbox("Select Target Truck", truck_list, key="bulk_del_truck")
                target_truck_id = truck_dict[target_truck]

                min_d = history_df['date_parsed'].min().date()
                max_d = history_df['date_parsed'].max().date()
                
                date_range = col_b2.date_input("Select Date Range to Clear", value=(min_d, max_d), key="bulk_del_dates")

                suppliers_for_bulk = ["All Suppliers"] + supplier_list
                selected_bulk_supplier = col_b1.selectbox("Filter by Supplier (Optional)", suppliers_for_bulk, key="bulk_del_supplier")
                target_supplier_id = supplier_dict.get(selected_bulk_supplier) if selected_bulk_supplier != "All Suppliers" else None

                if st.button("💥 PROCEED TO BULK DELETE", type="primary"):
                    if isinstance(date_range, tuple) and len(date_range) == 2:
                        confirm_bulk_delete_dialog(
                            conn, cursor, 
                            target_truck_id, target_truck, 
                            date_range[0], date_range[1], 
                            target_supplier_id
                        )
                    else:
                        st.error("Please select both a start date and end date.")

            # 3. DETAILED LIST WITH EDIT & SINGLE DELETE
            else:
                with st.container(border=True):
                    st.markdown("⚡ **Filter Controls**")
                    col_f1, col_f2 = st.columns(2)
                    
                    min_date = history_df['date_parsed'].min().date()
                    max_date = history_df['date_parsed'].max().date()
                    selected_dates = col_f1.date_input("Filter by Date Range", value=(min_date, max_date))
                    selected_trucks = col_f2.multiselect("Filter by Truck Number", options=list(history_df['truck'].unique()))
                    
                    col_f3, col_f4 = st.columns(2)
                    type_filter = col_f3.selectbox(
                        "Filter by Transaction Name/Type", 
                        ["All Transactions", "Standard Uplift (IN)", "Standard Delivery (OUT)", "Internal Transfers Only"]
                    )
                    search_query = col_f4.text_input("Global Search (Supplier name, ID, User, etc.)", "").strip().lower()

                filtered_df = history_df.copy()

                if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
                    filtered_df = filtered_df[
                        (filtered_df['date_parsed'].dt.date >= selected_dates[0]) & 
                        (filtered_df['date_parsed'].dt.date <= selected_dates[1])
                    ]
                
                if selected_trucks:
                    filtered_df = filtered_df[filtered_df['truck'].isin(selected_trucks)]
                
                if type_filter == "Standard Uplift (IN)":
                    filtered_df = filtered_df[(filtered_df['type'] == 'IN') & (filtered_df['transfer_partner_id'].isna())]
                elif type_filter == "Standard Delivery (OUT)":
                    filtered_df = filtered_df[(filtered_df['type'] == 'OUT') & (filtered_df['transfer_partner_id'].isna())]
                elif type_filter == "Internal Transfers Only":
                    filtered_df = filtered_df[filtered_df['transfer_partner_id'].notna()]

                if search_query:
                    filtered_df = filtered_df[
                        (filtered_df['supplier_name'].str.lower().str.contains(search_query, na=False)) |
                        (filtered_df['truck'].str.lower().str.contains(search_query, na=False)) |
                        (filtered_df['created_by'].str.lower().str.contains(search_query, na=False)) |
                        (filtered_df['id'].astype(str).str.contains(search_query))
                    ]

                # EXCEL DOWNLOAD BUTTON GENERATION
                col_info, col_download = st.columns([3, 1])
                col_info.markdown(f"Showing **{len(filtered_df)}** matching transaction actions:")

                if not filtered_df.empty:
                    export_df = filtered_df.copy()
                    export_df['Context'] = export_df.apply(
                        lambda r: f"Transfer ({'IN' if r['type']=='IN' else 'OUT'})" if pd.notna(r['transfer_partner_id']) 
                        else (f"Uplift [{r['supplier_name']}]" if r['type'] == 'IN' else "Delivery"), axis=1
                    )
                    
                    export_df = export_df.rename(columns={
                        'id': 'Transaction ID',
                        'date': 'Date',
                        'truck': 'Truck',
                        'liters': 'Liters',
                        'type': 'Type',
                        'supplier_name': 'Supplier Name',
                        'created_by': 'Created By'
                    })[['Transaction ID', 'Date', 'Truck', 'Type', 'Liters', 'Context', 'Supplier Name', 'Created By']]

                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        export_df.to_excel(writer, index=False, sheet_name='Detailed Transactions')
                    
                    col_download.download_button(
                        label="📥 Download Excel",
                        data=buffer.getvalue(),
                        file_name=f"Transaction_Records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )

                col_h1, col_h2, col_h3, col_h4, col_h5, col_h6, col_h7 = st.columns([2, 3, 2, 3, 2, 2, 2])
                col_h1.markdown("**Date**")
                col_h2.markdown("**Truck**")
                col_h3.markdown("**Quantity**")
                col_h4.markdown("**Context**")
                col_h5.markdown("**By**")
                col_h6.markdown("**ID**")
                col_h7.markdown("**Actions**")
                st.markdown("---")

                for _, item in filtered_df.iterrows():
                    col1, col2, col3, col4, col5, col6, col7 = st.columns([2, 3, 2, 3, 2, 2, 2])
                    col1.write(item["date"])
                    col2.write(f"🚛 {item['truck']}")
                    col3.write(f"**{item['liters']:,.2f} L**")
                    
                    if item['transfer_partner_id']:
                        ctx = f"🔄 Transfer ({'IN' if item['type']=='IN' else 'OUT'})"
                    else:
                        ctx = f"📥 Uplift [{item['supplier_name']}]" if item['type'] == 'IN' else "📤 Delivery"
                    
                    col4.write(ctx)
                    col5.write(f"👤 {item['created_by']}")
                    col6.write(f"`TX-{item['id']}`")
                    
                    edit_col, del_col = col7.columns(2)
                    
                    if edit_col.button("✏️", key=f"edit_{item['id']}"):
                        edit_transaction_dialog(conn, cursor, item, supplier_dict)

                    if del_col.button("🗑️", key=f"del_{item['id']}"):
                        cursor.execute("DELETE FROM transactions WHERE id = %s", (item['id'],))
                        if item['transfer_partner_id']:
                            cursor.execute("DELETE FROM transactions WHERE id = %s", (item['transfer_partner_id'],))
                        conn.commit()
                        log_action(cursor, conn, f"DELETED Transaction TX-{item['id']} ({item['liters']:,.2f} L for Truck '{item['truck']}')")
                        st.toast(f"Deleted TX-{item['id']} successfully!")
                        st.rerun()

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
