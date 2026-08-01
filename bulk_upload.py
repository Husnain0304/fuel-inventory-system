import streamlit as st
import pandas as pd
import re

def render_bulk_upload(conn, cursor, truck_dict, truck_list):
    st.title("📥 Bulk Delivery Upload")
    
    st.info("💡 Upload Excel with columns: **date** (DD-MM-YYYY), **truck**, **liters**, and **ticket_number**")

    # 1. Initialize tracking table for uploaded files
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id SERIAL PRIMARY KEY,
            file_name VARCHAR(255) UNIQUE,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. Ensure ticket_number column exists in transactions table
    cursor.execute("""
        ALTER TABLE transactions 
        ADD COLUMN IF NOT EXISTS ticket_number TEXT;
    """)
    conn.commit()

    # Session State Management for Staged Data and File Uploader Control Key
    if "uploader_key" not in st.session_state:
        st.session_state["uploader_key"] = 0
    if "staged_df" not in st.session_state:
        st.session_state["staged_df"] = None
    if "staged_filename" not in st.session_state:
        st.session_state["staged_filename"] = ""

    uploaded_file = st.file_uploader(
        "Upload Excel File", 
        type=["xlsx", "xls"], 
        key=f"excel_uploader_{st.session_state['uploader_key']}"
    )

    # -------------------------------------------------------------
    # 1. PARSE & STAGE EXCEL DATA
    # -------------------------------------------------------------
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

        # Parse File into Session State Staging Area if new or updated
        if st.session_state["staged_df"] is None or st.session_state["staged_filename"] != file_name:
            try:
                raw_df = pd.read_excel(uploaded_file)
                
                # Standardize column header names (e.g., "Ticket No", "ticket_number", "Ticket" -> "ticket_number")
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
                    st.error("❌ **Upload Failed!** Missing required columns. Your file must contain: `date`, `truck`, and `liters` (and optionally `ticket_number`).")
                    return

                # If ticket_number is not in Excel, create an empty column for manual entry
                if "ticket_number" not in raw_df.columns:
                    raw_df["ticket_number"] = ""

                # Clean & convert values to standard usable types for data editor
                raw_df['date'] = raw_df['date'].astype(str).str.strip()
                raw_df['truck'] = raw_df['truck'].astype(str).str.strip()
                raw_df['liters'] = pd.to_numeric(raw_df['liters'], errors='coerce').fillna(0.0)
                raw_df['ticket_number'] = raw_df['ticket_number'].fillna("").astype(str).str.strip()

                st.session_state["staged_df"] = raw_df[['date', 'truck', 'liters', 'ticket_number']].copy()
                st.session_state["staged_filename"] = file_name
            except Exception as e:
                st.error(f"❌ **Upload Failed!** Could not read Excel file structure: {str(e)}")
                return

    # -------------------------------------------------------------
    # 2. REVIEW, EDIT, & CONFIRM STAGED RECORDS
    # -------------------------------------------------------------
    if st.session_state["staged_df"] is not None:
        st.markdown("---")
        st.subheader(f"📋 Reviewing Uploaded File: `{st.session_state['staged_filename']}`")
        st.write("Edit cells directly in the table below (including Ticket Numbers) or delete rows before saving:")

        # Interactive Data Editor for Row Editing & Deletion
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

        # Action Buttons
        col_confirm, col_discard = st.columns([2, 1])

        # DISCARD FILE
        if col_discard.button("🗑️ Discard Uploaded File", use_container_width=True):
            st.session_state["staged_df"] = None
            st.session_state["staged_filename"] = ""
            st.session_state["uploader_key"] += 1
            st.warning("File preview discarded.")
            st.rerun()

        # CONFIRM AND PROCESS IMPORT
        if col_confirm.button("✅ Confirm & Import All Entries", type="primary", use_container_width=True):
            if edited_df.empty:
                st.error("❌ No data rows available to import!")
                return

            inserted_ids = []
            added_records = []
            skipped_records = []
            error_records = []

            # Validation Regex Rules
            pattern_with_code = re.compile(r'^[A-Z]{3}\s[A-Z0-9]{1,2}\s\d{1,5}$')
            pattern_no_code = re.compile(r'^[A-Z]{3}\s\d{1,5}$')
            pattern_serial = re.compile(r'^\d{1,5}$')

            # Process each staging row
            for index, row in edited_df.iterrows():
                row_num = index + 2
                raw_date = str(row['date']).strip()
                raw_truck = str(row['truck']).strip()
                raw_liters = row['liters']
                raw_ticket = str(row['ticket_number']).strip() if pd.notna(row['ticket_number']) else ""

                failed_fields = []
                errors = []

                # Date Format Validation
                parsed_date = None
                try:
                    parsed_date = pd.to_datetime(raw_date, format="%d-%m-%Y").date()
                except Exception:
                    try:
                        parsed_date = pd.to_datetime(raw_date).date()
                    except Exception:
                        errors.append("Invalid date format (Use DD-MM-YYYY)")
                        failed_fields.append("Date")

                # Liters Check
                try:
                    liters_val = float(raw_liters)
                    if liters_val <= 0:
                        errors.append("Liters must be greater than 0")
                        failed_fields.append("Liters")
                except (ValueError, TypeError):
                    errors.append("Liters must be numeric")
                    failed_fields.append("Liters")

                # Truck Registration & Format Check
                is_valid_format = False
                if "gen" in raw_truck.lower():
                    is_valid_format = True
                elif (pattern_with_code.match(raw_truck) or 
                      pattern_no_code.match(raw_truck) or 
                      pattern_serial.match(raw_truck)):
                    is_valid_format = True

                if raw_truck not in truck_dict:
                    errors.append(f"Truck '{raw_truck}' is not registered in system")
                    failed_fields.append("Truck")
                elif not is_valid_format:
                    errors.append(f"Format mismatch in '{raw_truck}'")
                    failed_fields.append("Truck")

                # Ticket Number Check (If you want ticket number to be strictly mandatory, uncomment below)
                # if not raw_ticket:
                #     errors.append("Ticket Number is required")
                #     failed_fields.append("Ticket Number")

                # Log formatting errors
                if errors:
                    error_records.append({
                        "Row": row_num,
                        "Truck": raw_truck,
                        "Date": raw_date,
                        "Liters": raw_liters,
                        "Ticket No": raw_ticket,
                        "Reason": " | ".join(errors)
                    })
                    continue

                # Duplicate Transaction Check against DB (Checks Truck, Date, Liters, and Ticket Number)
                truck_id = truck_dict[raw_truck]
                dup_check = pd.read_sql_query("""
                    SELECT id FROM transactions 
                    WHERE truck_id = %s AND date = %s AND liters = %s AND type = 'OUT'
                      AND (ticket_number = %s OR (ticket_number IS NULL AND %s = ''))
                """, conn, params=[truck_id, str(parsed_date), liters_val, raw_ticket, raw_ticket])

                if not dup_check.empty:
                    skipped_records.append({
                        "Row": row_num,
                        "Truck": raw_truck,
                        "Date": str(parsed_date),
                        "Liters": f"{liters_val:,.2f} L",
                        "Ticket No": raw_ticket,
                        "Reason": "Duplicate transaction already in database"
                    })
                else:
                    # Insert Valid Delivery Entry with Ticket Number
                    cursor.execute("""
                        INSERT INTO transactions (truck_id, date, liters, type, ticket_number) 
                        VALUES (%s, %s, %s, 'OUT', %s) RETURNING id
                    """, (truck_id, str(parsed_date), liters_val, raw_ticket))
                    
                    last_id = cursor.fetchone()[0]
                    inserted_ids.append(last_id)
                    added_records.append({
                        "id": last_id,
                        "Truck": raw_truck,
                        "Date": str(parsed_date),
                        "Liters": liters_val,
                        "Ticket No": raw_ticket
                    })

            # Handle Commit & Cleanup
            if added_records:
                conn.commit()
                
                # Log uploaded file name to prevent duplicate upload re-runs
                cursor.execute("""
                    INSERT INTO uploaded_files (file_name) VALUES (%s)
                    ON CONFLICT (file_name) DO UPDATE SET uploaded_at = CURRENT_TIMESTAMP
                """, (st.session_state["staged_filename"],))
                conn.commit()

                total_liters = sum([r["Liters"] for r in added_records])
                st.success(f"🎉 **Import Successful!** {len(added_records)} delivery transactions added ({total_liters:,.2f} L total).")

                # Reset Staging & Clear File Uploader Input
                st.session_state["staged_df"] = None
                st.session_state["staged_filename"] = ""
                st.session_state["uploader_key"] += 1
                st.rerun()

            elif skipped_records or error_records:
                st.error("❌ **Upload Failed!** No records were imported into the database due to duplicate entries or formatting errors.")
                
                if skipped_records:
                    st.warning(f"ℹ️ **Skipped Duplicates ({len(skipped_records)}):**")
                    st.dataframe(pd.DataFrame(skipped_records), use_container_width=True, hide_index=True)

                if error_records:
                    st.error(f"🚨 **Formatting Errors ({len(error_records)}):**")
                    st.dataframe(pd.DataFrame(error_records), use_container_width=True, hide_index=True)
