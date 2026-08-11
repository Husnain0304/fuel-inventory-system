import streamlit as st
import pandas as pd
import re

def render_bulk_upload(conn, cursor, truck_dict, truck_list):
    st.title("📥 Bulk Delivery Upload & File Management")

    # Reverse lookup map for truck ID to Name
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

    # Persistent Success Banner
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
            cursor.execute("SELECT uploaded_at FROM uploaded_files WHERE file_name = %s", (file_name,))
            duplicate_row = cursor.fetchone()

            if duplicate_row and st.session_state["staged_filename"] != file_name:
                upload_time = duplicate_row[0]
                st.error(f"⚠️ **Duplicate File Detected!**\n\nThe file **'{file_name}'** was already imported on `{upload_time}`.")
                bypass_upload = st.checkbox("🔄 Force re-upload/re-stage this file anyway.")
                if not bypass_upload:
                    st.warning("Please rename your file, or delete the existing file record under 'File History & Management'.")
                    return

            # Parse File into Session State Staging Area
            if st.session_state["staged_df"] is None or st.session_state["staged_filename"] != file_name:
                try:
                    raw_df = pd.read_excel(uploaded_file)
                    
                    # Standardize column header names
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

                    # Clean data types safely
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
                    "date": st.column_config.TextColumn("Date (DD-MM-YYYY)", required=True),
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

                error_records = []
                parsed_rows = []

                pattern_with_code = re.compile(r'^[A-Z]{3}\s[A-Z0-9]{1,2}\s\d{1,5}$')
                pattern_no_code = re.compile(r'^[A-Z]{3}\s\d{1,5}$')
                pattern_serial = re.compile(r'^\d{1,5}$')

                # Validate rows in memory before modifying DB state
                for index, row in edited_df.iterrows():
                    row_num = index + 2
                    raw_date = str(row['date']).strip()
                    raw_truck = str(row['truck']).strip().upper()
                    raw_liters = row['liters']
                    raw_ticket = str(row['ticket_number']).strip() if pd.notna(row['ticket_number']) else ""

                    row_errors = []

                    # Parse Date safely
                    parsed_date = None
                    try:
                        parsed_date = pd.to_datetime(raw_date, dayfirst=True).date()
                    except Exception:
                        row_errors.append("Invalid date format (Use DD-MM-YYYY)")

                    # Parse Liters
                    try:
                        liters_val = float(raw_liters)
                        if liters_val <= 0:
                            row_errors.append("Liters must be > 0")
                    except (ValueError, TypeError):
                        row_errors.append("Liters must be numeric")

                    # Truck Verification
                    is_valid_format = "GEN" in raw_truck or pattern_with_code.match(raw_truck) or pattern_no_code.match(raw_truck) or pattern_serial.match(raw_truck)
                    
                    matched_truck_id = next((v for k, v in truck_dict.items() if k.upper() == raw_truck), None)

                    if not matched_truck_id:
                        row_errors.append(f"Truck '{raw_truck}' not registered")
                    elif not is_valid_format:
                        row_errors.append(f"Format mismatch in '{raw_truck}'")

                    if row_errors:
                        error_records.append({
                            "Row": row_num, "Truck": raw_truck, "Date": raw_date,
                            "Liters": raw_liters, "Ticket No": raw_ticket, "Reason": " | ".join(row_errors)
                        })
                    else:
                        parsed_rows.append({
                            "row_num": row_num, "truck_id": matched_truck_id, "truck_name": raw_truck,
                            "date": str(parsed_date), "liters": liters_val, "ticket": raw_ticket
                        })

                if error_records:
                    st.error(f"🚨 **Formatting Errors Found ({len(error_records)}):** Import stopped.")
                    st.dataframe(pd.DataFrame(error_records), use_container_width=True, hide_index=True)
                    return

                # Database Execution Phase (Atomic Transaction)
                try:
                    cursor.execute("""
                        INSERT INTO uploaded_files (file_name) VALUES (%s)
                        ON CONFLICT (file_name) DO UPDATE SET uploaded_at = CURRENT_TIMESTAMP
                        RETURNING id;
                    """, (st.session_state["staged_filename"],))
                    file_id = cursor.fetchone()[0]

                    added_records = []
                    skipped_records = []

                    for item in parsed_rows:
                        cursor.execute("""
                            SELECT id FROM transactions 
                            WHERE truck_id = %s AND date = %s AND liters = %s AND type = 'OUT'
                              AND (ticket_number = %s OR (ticket_number IS NULL AND %s = ''))
                        """, (item["truck_id"], item["date"], item["liters"], item["ticket"], item["ticket"]))
                        
                        if cursor.fetchone():
                            skipped_records.append({
                                "Row": item["row_num"], "Truck": item["truck_name"], "Date": item["date"],
                                "Liters": f"{item['liters']:,.2f} L", "Ticket No": item["ticket"], "Reason": "Duplicate transaction"
                            })
                        else:
                            cursor.execute("""
                                INSERT INTO transactions (truck_id, date, liters, type, ticket_number, file_id) 
                                VALUES (%s, %s, %s, 'OUT', %s, %s) RETURNING id
                            """, (item["truck_id"], item["date"], item["liters"], item["ticket"], file_id))
                            added_records.append(item["liters"])

                    conn.commit()

                    if added_records:
                        total_liters = sum(added_records)
                        st.session_state["upload_success_msg"] = (
                            f"🎉 **Import Successful!** Processed `{st.session_state['staged_filename']}` — "
                            f"**{len(added_records)}** transactions added (**{total_liters:,.2f} L** total)."
                        )
                        st.session_state["staged_df"] = None
                        st.session_state["staged_filename"] = ""
                        st.session_state["uploader_key"] += 1
                        st.rerun()

                    elif skipped_records:
                        st.warning(f"ℹ️ **All records were duplicates ({len(skipped_records)} skipped):**")
                        st.dataframe(pd.DataFrame(skipped_records), use_container_width=True, hide_index=True)

                except Exception as e:
                    conn.rollback()
                    st.error(f"❌ **Database Import Failed:** {str(e)}")

    # =============================================================
    # TAB 2: FILE HISTORY & FILE-WISE TRANSACTIONS
    # =============================================================
    with tab_history:
        st.subheader("📁 Uploaded Files Directory")

        cursor.execute("""
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
        """)
        file_rows = cursor.fetchall()
        file_cols = [desc[0] for desc in cursor.description]
        files_df = pd.DataFrame(file_rows, columns=file_cols)

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

            cursor.execute("""
                SELECT id, date, truck_id, liters, ticket_number 
                FROM transactions 
                WHERE file_id = %s 
                ORDER BY date DESC, id DESC;
            """, (sel_file_id,))
            tx_rows = cursor.fetchall()
            tx_cols = [desc[0] for desc in cursor.description]
            tx_df = pd.DataFrame(tx_rows, columns=tx_cols)

            if tx_df.empty:
                st.warning("No transactions remaining under this file.")
            else:
                tx_df["truck"] = tx_df["truck_id"].map(truck_id_to_name)
                display_df = tx_df[["id", "date", "truck", "liters", "ticket_number"]].copy()

                # Fix for StreamlitAPIException: convert date column to pandas datetime64
                display_df["date"] = pd.to_datetime(display_df["date"])

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
                        current_ids = edited_tx["id"].dropna().tolist()
                        deleted_ids = set(tx_df["id"]) - set(current_ids)

                        for d_id in deleted_ids:
                            cursor.execute("DELETE FROM transactions WHERE id = %s", (d_id,))

                        for _, row in edited_tx.iterrows():
                            if pd.notna(row["id"]):
                                t_id = truck_dict.get(row["truck"])
                                # Format date back to string for database update
                                date_str = pd.to_datetime(row["date"]).strftime("%Y-%m-%d") if pd.notna(row["date"]) else str(row["date"])
                                cursor.execute("""
                                    UPDATE transactions 
                                    SET date = %s, truck_id = %s, liters = %s, ticket_number = %s
                                    WHERE id = %s
                                """, (date_str, t_id, row["liters"], str(row["ticket_number"]), int(row["id"])))

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

        # Safely query files directory specifically for search tab dropdown
        cursor.execute("SELECT file_name FROM uploaded_files ORDER BY file_name ASC;")
        db_files = [r[0] for r in cursor.fetchall()]

        col_s1, col_s2, col_s3 = st.columns(3)
        search_ticket = col_s1.text_input("Search Ticket Number", placeholder="e.g. T-10293")
        search_truck = col_s2.selectbox("Filter by Truck", ["All Trucks"] + truck_list)
        search_file = col_s3.selectbox("Filter by Source File", ["All Files"] + db_files)

        col_d1, col_d2, col_l1, col_l2 = st.columns(4)
        start_date = col_d1.date_input("Start Date", value=None)
        end_date = col_d2.date_input("End Date", value=None)
        min_liters = col_l1.number_input("Min Liters", min_value=0.0, value=0.0)
        max_liters = col_l2.number_input("Max Liters", min_value=0.0, value=0.0)

        query = """
            SELECT 
                t.id, 
                t.date, 
                t.truck_id, 
                t.liters, 
                t.ticket_number, 
                COALESCE(f.file_name, 'Manual Entry') AS source_file
            FROM transactions t
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

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        colnames = [desc[0] for desc in cursor.description]
        results_df = pd.DataFrame(rows, columns=colnames)

        if not results_df.empty:
            results_df["truck"] = results_df["truck_id"].map(truck_id_to_name)
            results_df = results_df[["id", "date", "truck", "liters", "ticket_number", "source_file"]]

        st.markdown(f"**Found {len(results_df)} matching record(s)**")
        st.dataframe(
            results_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.NumberColumn("Tx ID"),
                "date": st.column_config.DateColumn("Date"),
                "truck": st.column_config.TextColumn("Truck"),
                "liters": st.column_config.NumberColumn("Liters", format="%.2f L"),
                "ticket_number": st.column_config.TextColumn("Ticket Number"),
                "source_file": st.column_config.TextColumn("Uploaded File Source")
            }
        )
