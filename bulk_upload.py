import streamlit as st
import pandas as pd
import re

def render_bulk_upload(conn, cursor, truck_dict, truck_list):
    st.title("📥 Bulk Delivery Upload & File Management")

    # -------------------------------------------------------------
    # DB SCHEMA INITIALIZATION & MIGRATIONS
    # -------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id SERIAL PRIMARY KEY,
            file_name VARCHAR(255) UNIQUE,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cursor.execute("""
        ALTER TABLE transactions 
        ADD COLUMN IF NOT EXISTS ticket_number TEXT,
        ADD COLUMN IF NOT EXISTS file_id INTEGER REFERENCES uploaded_files(id) ON DELETE CASCADE;
    """)
    conn.commit()

    # Create reverse dictionary for truck ID to Name lookups
    truck_id_to_name = {v: k for k, v in truck_dict.items()}

    # Session State Management
    if "uploader_key" not in st.session_state:
        st.session_state["uploader_key"] = 0
    if "staged_df" not in st.session_state:
        st.session_state["staged_df"] = None
    if "staged_filename" not in st.session_state:
        st.session_state["staged_filename"] = ""
    if "upload_success_msg" not in st.session_state:
        st.session_state["upload_success_msg"] = None

    # Persistent Success Banner (Displays post rerun)
    if st.session_state["upload_success_msg"]:
        st.success(st.session_state["upload_success_msg"])
        st.session_state["upload_success_msg"] = None

    # Navigation Tabs
    tab_upload, tab_history, tab_search = st.tabs([
        "📤 New File Upload", 
        "📁 File History & Management", 
        "🔍 Search Transactions"
    ])

    # =============================================================
    # TAB 1: NEW FILE UPLOAD
    # =============================================================
    with tab_upload:
        st.info("💡 Upload Excel with columns: **date** (DD-MM-YYYY), **truck**, **liters**, and **ticket_number**")

        uploaded_file = st.file_uploader(
            "Upload Excel File", 
            type=["xlsx", "xls"], 
            key=f"excel_uploader_{st.session_state['uploader_key']}"
        )

        if uploaded_file is not None:
            file_name = uploaded_file.name

            # Check for Duplicate File Name
            duplicate_file_check = pd.read_sql_query(
                "SELECT uploaded_at FROM uploaded_files WHERE file_name = %s", 
                conn, 
                params=[file_name]
            )

            bypass_upload = False
            if not duplicate_file_check.empty:
                upload_time = duplicate_file_check.iloc[0]["uploaded_at"]
                st.error(f"⚠️ **Duplicate File Detected!**\n\nThe file **'{file_name}'** was already imported on `{upload_time}`.")
                bypass_upload = st.checkbox("🔄 Force re-upload/re-stage this file anyway.")
                if not bypass_upload:
                    st.warning("Please rename your file, or check the box above to force parsing.")
                    return

            # Parse File into Session State
            if st.session_state["staged_df"] is None or st.session_state["staged_filename"] != file_name:
                try:
                    raw_df = pd.read_excel(uploaded_file)
                    
                    # Standardize column headers
                    col_map = {}
                    for c in raw_df.columns:
                        c_clean = str(c).strip().lower().replace(" ", "_").replace(".", "")
                        if c_clean in ["ticket", "ticket_no", "ticket_number", "ticketno"]:
                            col_map[c] = "ticket_number"
                        elif c_clean in ["date", "truck", "liters"]:
                            col_map[c] = c_clean
                    
                    raw_df = raw_df.rename(columns=col_map)
                    
                    required_cols = {"date", "truck", "liters"}
                    if not required_cols.issubset(set(raw_df.columns)):
                        st.error("❌ **Upload Failed!** Missing required columns (`date`, `truck`, `liters`).")
                        return

                    if "ticket_number" not in raw_df.columns:
                        raw_df["ticket_number"] = ""

                    # Clean data formatting
                    raw_df['date'] = raw_df['date'].astype(str).str.strip()
                    raw_df['truck'] = raw_df['truck'].astype(str).str.strip()
                    raw_df['liters'] = pd.to_numeric(raw_df['liters'], errors='coerce').fillna(0.0)
                    raw_df['ticket_number'] = raw_df['ticket_number'].fillna("").astype(str).str.strip()

                    st.session_state["staged_df"] = raw_df[['date', 'truck', 'liters', 'ticket_number']].copy()
                    st.session_state["staged_filename"] = file_name
                except Exception as e:
                    st.error(f"❌ **Upload Failed!** Could not read Excel structure: {str(e)}")
                    return

        # Review & Edit Staged Records
        if st.session_state["staged_df"] is not None:
            st.markdown("---")
            st.subheader(f"📋 Reviewing Uploaded File: `{st.session_state['staged_filename']}`")
            st.write("Edit cells directly in the table below or delete rows before confirming:")

            edited_df = st.data_editor(
                st.session_state["staged_df"],
                num_rows="dynamic",
                use_container_width=True,
                column_config={
                    "date": st.column_config.TextColumn("Date (DD-MM-YYYY or YYYY-MM-DD)", required=True),
                    "truck": st.column_config.TextColumn("Truck Number / Plate", required=True),
                    "liters": st.column_config.NumberColumn("Liters (Fuel Out)", min_value=0.01, format="%.2f L", required=True),
                    "ticket_number": st.column_config.TextColumn("Ticket Number", required=False)
                },
                key="bulk_data_editor"
            )

            st.session_state["staged_df"] = edited_df

            col_confirm, col_discard = st.columns([2, 1])

            if col_discard.button("🗑️ Discard Uploaded File", use_container_width=True):
                st.session_state["staged_df"] = None
                st.session_state["staged_filename"] = ""
                st.session_state["uploader_key"] += 1
                st.warning("File preview discarded.")
                st.rerun()

            if col_confirm.button("✅ Confirm & Import All Entries", type="primary", use_container_width=True):
                if edited_df.empty:
                    st.error("❌ No data rows available to import!")
                    return

                added_records = []
                skipped_records = []
                error_records = []

                pattern_with_code = re.compile(r'^[A-Z]{3}\s[A-Z0-9]{1,2}\s\d{1,5}$')
                pattern_no_code = re.compile(r'^[A-Z]{3}\s\d{1,5}$')
                pattern_serial = re.compile(r'^\d{1,5}$')

                # Register File in uploaded_files table
                cursor.execute("""
                    INSERT INTO uploaded_files (file_name) VALUES (%s)
                    ON CONFLICT (file_name) DO UPDATE SET uploaded_at = CURRENT_TIMESTAMP
                    RETURNING id;
                """, (st.session_state["staged_filename"],))
                file_id = cursor.fetchone()[0]

                for index, row in edited_df.iterrows():
                    row_num = index + 2
                    raw_date = str(row['date']).strip()
                    raw_truck = str(row['truck']).strip()
                    raw_liters = row['liters']
                    raw_ticket = str(row['ticket_number']).strip() if pd.notna(row['ticket_number']) else ""

                    errors = []

                    # Parse Date
                    parsed_date = None
                    try:
                        parsed_date = pd.to_datetime(raw_date, format="%d-%m-%Y").date()
                    except Exception:
                        try:
                            parsed_date = pd.to_datetime(raw_date).date()
                        except Exception:
                            errors.append("Invalid date format (Use DD-MM-YYYY)")

                    # Parse Liters
                    try:
                        liters_val = float(raw_liters)
                        if liters_val <= 0:
                            errors.append("Liters must be > 0")
                    except (ValueError, TypeError):
                        errors.append("Liters must be numeric")

                    # Truck Check
                    is_valid_format = "gen" in raw_truck.lower() or pattern_with_code.match(raw_truck) or pattern_no_code.match(raw_truck) or pattern_serial.match(raw_truck)
                    if raw_truck not in truck_dict:
                        errors.append(f"Truck '{raw_truck}' not registered")
                    elif not is_valid_format:
                        errors.append(f"Format mismatch in '{raw_truck}'")

                    if errors:
                        error_records.append({
                            "Row": row_num, "Truck": raw_truck, "Date": raw_date,
                            "Liters": raw_liters, "Ticket No": raw_ticket, "Reason": " | ".join(errors)
                        })
                        continue

                    # Duplicate Check
                    truck_id = truck_dict[raw_truck]
                    dup_check = pd.read_sql_query("""
                        SELECT id FROM transactions 
                        WHERE truck_id = %s AND date = %s AND liters = %s AND type = 'OUT'
                          AND (ticket_number = %s OR (ticket_number IS NULL AND %s = ''))
                    """, conn, params=[truck_id, str(parsed_date), liters_val, raw_ticket, raw_ticket])

                    if not dup_check.empty:
                        skipped_records.append({
                            "Row": row_num, "Truck": raw_truck, "Date": str(parsed_date),
                            "Liters": f"{liters_val:,.2f} L", "Ticket No": raw_ticket, "Reason": "Duplicate transaction"
                        })
                    else:
                        cursor.execute("""
                            INSERT INTO transactions (truck_id, date, liters, type, ticket_number, file_id) 
                            VALUES (%s, %s, %s, 'OUT', %s, %s) RETURNING id
                        """, (truck_id, str(parsed_date), liters_val, raw_ticket, file_id))
                        
                        last_id = cursor.fetchone()[0]
                        added_records.append({"id": last_id, "Liters": liters_val})

                if added_records:
                    conn.commit()
                    total_liters = sum([r["Liters"] for r in added_records])
                    
                    st.session_state["upload_success_msg"] = (
                        f"🎉 **Import Successful!** Processed `{st.session_state['staged_filename']}` — "
                        f"**{len(added_records)}** transactions added (**{total_liters:,.2f} L** total)."
                    )

                    # Reset Staging Area
                    st.session_state["staged_df"] = None
                    st.session_state["staged_filename"] = ""
                    st.session_state["uploader_key"] += 1
                    st.rerun()

                elif skipped_records or error_records:
                    conn.rollback()
                    st.error("❌ **Upload Failed!** No records were imported.")
                    if skipped_records:
                        st.warning(f"ℹ️ **Skipped Duplicates ({len(skipped_records)}):**")
                        st.dataframe(pd.DataFrame(skipped_records), use_container_width=True, hide_index=True)
                    if error_records:
                        st.error(f"🚨 **Formatting Errors ({len(error_records)}):**")
                        st.dataframe(pd.DataFrame(error_records), use_container_width=True, hide_index=True)

    # =============================================================
    # TAB 2: FILE HISTORY & FILE-WISE TRANSACTIONS
    # =============================================================
    with tab_history:
        st.subheader("📁 Uploaded Files Directory")

        files_df = pd.read_sql_query("""
            SELECT 
                f.id AS file_id,
                f.file_name,
                f.uploaded_at,
                COUNT(t.id) AS total_transactions,
                COALESCE(SUM(t.liters), 0.0) AS total_liters
            FROM uploaded_files f
            LEFT JOIN transactions t ON f.id = t.file_id
            GROUP BY f.id, f.file_name, f.uploaded_at
            ORDER BY f.uploaded_at DESC;
        """, conn)

        if files_df.empty:
            st.info("No files have been uploaded yet.")
        else:
            selected_file = st.selectbox(
                "Select File to View Transactions / Manage File:",
                files_df["file_name"].tolist(),
                key="selected_file_history"
            )

            file_info = files_df[files_df["file_name"] == selected_file].iloc[0]
            sel_file_id = int(file_info["file_id"])

            m1, m2, m3 = st.columns(3)
            m1.metric("Uploaded On", str(file_info["uploaded_at"])[:16])
            m2.metric("Total Transactions", f"{file_info['total_transactions']:,}")
            m3.metric("Total Liters", f"{file_info['total_liters']:,.2f} L")

            st.markdown("---")
            st.write(f"### 📄 Transactions in `{selected_file}`")

            # Fetch file transactions
            tx_df = pd.read_sql_query("""
                SELECT id, date, truck_id, liters, ticket_number 
                FROM transactions 
                WHERE file_id = %s 
                ORDER BY date DESC, id DESC;
            """, conn, params=[sel_file_id])

            if tx_df.empty:
                st.warning("No transactions remaining under this file.")
            else:
                tx_df["truck"] = tx_df["truck_id"].map(truck_id_to_name)
                display_df = tx_df[["id", "date", "truck", "liters", "ticket_number"]].copy()

                edited_tx = st.data_editor(
                    display_df,
                    key=f"file_tx_editor_{sel_file_id}",
                    num_rows="dynamic",
                    use_container_width=True,
                    column_config={
                        "id": st.column_config.NumberColumn("ID", disabled=True),
                        "date": st.column_config.DateColumn("Date", required=True),
                        "truck": st.column_config.SelectboxColumn("Truck", options=truck_list, required=True),
                        "liters": st.column_config.NumberColumn("Liters", format="%.2f L", required=True),
                        "ticket_number": st.column_config.TextColumn("Ticket Number")
                    }
                )

                col_save, col_del_file = st.columns([2, 1])

                if col_save.button("💾 Save Changes to File Transactions", type="primary"):
                    try:
                        # Process updates/deletions
                        current_ids = edited_tx["id"].dropna().tolist()
                        deleted_ids = set(tx_df["id"]) - set(current_ids)

                        for d_id in deleted_ids:
                            cursor.execute("DELETE FROM transactions WHERE id = %s", (d_id,))

                        for _, row in edited_tx.iterrows():
                            if pd.notna(row["id"]):
                                t_id = truck_dict.get(row["truck"])
                                cursor.execute("""
                                    UPDATE transactions 
                                    SET date = %s, truck_id = %s, liters = %s, ticket_number = %s
                                    WHERE id = %s
                                """, (str(row["date"]), t_id, row["liters"], str(row["ticket_number"]), int(row["id"])))

                        conn.commit()
                        st.success("Transactions updated successfully!")
                        st.rerun()
                    except Exception as e:
                        conn.rollback()
                        st.error(f"Error saving updates: {e}")

                with col_del_file:
                    with st.expander("🗑️ Delete Entire File"):
                        st.warning("This will permanently remove this file and all associated transactions!")
                        if st.button(f"Confirm Delete '{selected_file}'", type="primary"):
                            cursor.execute("DELETE FROM uploaded_files WHERE id = %s", (sel_file_id,))
                            conn.commit()
                            st.success(f"File '{selected_file}' and its transactions were deleted.")
                            st.rerun()

    # =============================================================
    # TAB 3: SEARCH TRANSACTIONS
    # =============================================================
    with tab_search:
        st.subheader("🔍 Advanced Transaction Search")

        col_s1, col_s2, col_s3 = st.columns(3)
        search_ticket = col_s1.text_input("Search Ticket Number", placeholder="e.g. T-10293")
        search_truck = col_s2.selectbox("Filter by Truck", ["All Trucks"] + truck_list)
        search_file = col_s3.selectbox("Filter by Source File", ["All Files"] + files_df["file_name"].tolist() if not files_df.empty else ["All Files"])

        col_d1, col_d2, col_l1, col_l2 = st.columns(4)
        start_date = col_d1.date_input("Start Date", value=None)
        end_date = col_d2.date_input("End Date", value=None)
        min_liters = col_l1.number_input("Min Liters", min_value=0.0, value=0.0)
        max_liters = col_l2.number_input("Max Liters", min_value=0.0, value=0.0)

        # Dynamic Query Construction
        query = """
            SELECT 
                t.id, 
                t.date, 
                tr.truck_name, 
                t.liters, 
                t.ticket_number, 
                COALESCE(f.file_name, 'Manual Entry') AS source_file
            FROM transactions t
            LEFT JOIN trucks tr ON t.truck_id = tr.id
            LEFT JOIN uploaded_files f ON t.file_id = f.id
            WHERE 1=1
        """
        params = []

        if search_ticket:
            query += " AND t.ticket_number ILIKE %s"
            params.append(f"%{search_ticket.strip()}%")

        if search_truck != "All Trucks":
            query += " AND t.truck_id = %s"
            params.append(truck_dict[search_truck])

        if search_file != "All Files":
            query += " AND f.file_name = %s"
            params.append(search_file)

        if start_date:
            query += " AND t.date >= %s"
            params.append(str(start_date))

        if end_date:
            query += " AND t.date <= %s"
            params.append(str(end_date))

        if min_liters > 0:
            query += " AND t.liters >= %s"
            params.append(min_liters)

        if max_liters > 0 and max_liters >= min_liters:
            query += " AND t.liters <= %s"
            params.append(max_liters)

        query += " ORDER BY t.date DESC, t.id DESC LIMIT 500;"

        results_df = pd.read_sql_query(query, conn, params=params)

        st.markdown(f"**Found {len(results_df)} matching record(s)**")
        st.dataframe(
            results_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.NumberColumn("Tx ID"),
                "date": st.column_config.DateColumn("Date"),
                "truck_name": st.column_config.TextColumn("Truck"),
                "liters": st.column_config.NumberColumn("Liters", format="%.2f L"),
                "ticket_number": st.column_config.TextColumn("Ticket Number"),
                "source_file": st.column_config.TextColumn("Uploaded File Source")
            }
        )
