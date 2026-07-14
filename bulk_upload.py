import streamlit as st
import pandas as pd
import re

def render_bulk_upload(conn, cursor, truck_dict, truck_list):
    st.title("📥 Bulk Delivery Upload")
    
    st.info("💡 Upload Excel with columns: **date** (DD-MM-YYYY), **truck**, **liters**")

    # Initialize the tracking table if not already done
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT UNIQUE,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    if "last_imported_ids" not in st.session_state:
        st.session_state["last_imported_ids"] = []

    uploaded_file = st.file_uploader("Upload Excel File", type=["xlsx", "xls"])

    if uploaded_file is not None:
        file_name = uploaded_file.name

        # -------------------------------------------------------------
        # FILE NAME CHECK
        # -------------------------------------------------------------
        # Check if this file name has been uploaded before
        duplicate_file_check = pd.read_sql_query(
            "SELECT uploaded_at FROM uploaded_files WHERE file_name = ?", 
            conn, 
            params=[file_name]
        )

        bypass_upload = False

        if not duplicate_file_check.empty:
            upload_time = duplicate_file_check.iloc[0]["uploaded_at"]
            
            st.error(f"⚠️ **Duplicate File Detected!**\n\nThe file **'{file_name}'** was already uploaded on `{upload_time}`.")
            
            # Offer an override checkbox
            bypass_upload = st.checkbox("🔄 I have modified this file and want to force re-upload it anyway.")
            
            if not bypass_upload:
                st.warning("Please rename your file, or check the box above to force the upload.")
                return  # Stop processing the file right here

        # -------------------------------------------------------------
        # PROCESS EXCEL FILE
        # -------------------------------------------------------------
        try:
            df = pd.read_excel(uploaded_file)
            
            df.columns = [str(c).strip().lower() for c in df.columns]
            
            required_cols = {"date", "truck", "liters"}
            if not required_cols.issubset(set(df.columns)):
                st.error("❌ Missing required columns. Your file must contain: date, truck, and liters.")
                return

            inserted_ids = []
            added_records = []
            skipped_records = []
            error_records = []

            # Patterns
            pattern_with_code = re.compile(r'^[A-Z]{3}\s[A-Z0-9]{1,2}\s\d{1,5}$')
            pattern_no_code = re.compile(r'^[A-Z]{3}\s\d{1,5}$')
            pattern_serial = re.compile(r'^\d{1,5}$')

            for index, row in df.iterrows():
                row_num = index + 2
                
                raw_date = str(row['date']).strip()
                raw_truck = str(row['truck']).strip()
                raw_liters = row['liters']

                failed_fields = []
                errors = []

                # Date Format
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
                except ValueError:
                    errors.append("Liters must be a numeric value")
                    failed_fields.append("Liters")

                # Truck Check
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
                    errors.append(f"Format mismatch: Check spacing/characters in '{raw_truck}'")
                    failed_fields.append("Truck")

                if errors:
                    error_records.append({
                        "Excel Row": row_num,
                        "Truck": raw_truck,
                        "Date": raw_date,
                        "Liters": raw_liters,
                        "Reason/Error": " | ".join(errors),
                        "failed_fields": failed_fields
                    })
                    continue

                # Duplicate Transaction Check
                truck_id = truck_dict[raw_truck]
                dup_check = pd.read_sql_query("""
                    SELECT id FROM transactions 
                    WHERE truck_id = ? AND date = ? AND liters = ? AND type = 'OUT'
                """, conn, params=[truck_id, str(parsed_date), liters_val])

                if not dup_check.empty:
                    skipped_records.append({
                        "Excel Row": row_num,
                        "Truck": raw_truck,
                        "Date": str(parsed_date),
                        "Liters": f"{liters_val:,.2f} L",
                        "Reason": "Duplicate (Already exists in database)"
                    })
                else:
                    cursor.execute("""
                        INSERT INTO transactions (truck_id, date, liters, type) 
                        VALUES (?, ?, ?, 'OUT')
                    """, (truck_id, str(parsed_date), liters_val))
                    
                    last_id = cursor.lastrowid
                    inserted_ids.append(last_id)
                    
                    added_records.append({
                        "id": last_id,
                        "Excel Row": row_num,
                        "Truck": raw_truck,
                        "Date": str(parsed_date),
                        "Liters": liters_val
                    })

            # Commit additions and log file name
            if added_records:
                conn.commit()
                st.session_state["last_imported_ids"] = inserted_ids
                
                # Log filename so it can't be uploaded again without bypass
                cursor.execute(
                    "INSERT OR REPLACE INTO uploaded_files (file_name) VALUES (?)", 
                    (file_name,)
                )
                conn.commit()

            # ==========================================
            # 3. RENDER RESULTS & SUMMARY TABLES
            # ==========================================
            st.markdown("---")
            st.subheader("📊 Import Summary")

            # Success Section
            if added_records:
                added_df = pd.DataFrame(added_records)
                total_liters = added_df["Liters"].sum()
                st.success(f"🚀 Successfully Added: {len(added_records)} transactions! (Total: {total_liters:,.2f} Liters)")
                
                st.markdown("### 🔍 Verification Breakdown")
                verification_df = added_df.groupby("Truck")["Liters"].agg(["count", "sum"]).reset_index()
                verification_df.columns = ["Truck Number", "Total Entries Added", "Total Liters Added"]
                verification_df["Total Liters Added"] = verification_df["Total Liters Added"].apply(lambda x: f"{x:,.2f} L")
                st.dataframe(verification_df, use_container_width=True, hide_index=True)

                st.markdown("#### ⚠️ Mistake in imports?")
                if st.button("🗑️ Delete/Rollback Whole Transaction Upload", type="primary"):
                    if st.session_state["last_imported_ids"]:
                        ids_to_delete = st.session_state["last_imported_ids"]
                        placeholders = ",".join(["?"] * len(ids_to_delete))
                        cursor.execute(f"DELETE FROM transactions WHERE id IN ({placeholders})", ids_to_delete)
                        
                        # Also remove the file name log so they can upload it clean again
                        cursor.execute("DELETE FROM uploaded_files WHERE file_name = ?", (file_name,))
                        conn.commit()
                        
                        st.session_state["last_imported_ids"] = []
                        st.error("All transactions added from this file have been deleted.")
                        st.rerun()

                with st.expander("👉 View Row-by-Row Added Transactions", expanded=False):
                    display_added = added_df.copy()
                    display_added["Liters"] = display_added["Liters"].apply(lambda x: f"{x:,.2f} L")
                    st.dataframe(display_added[["Excel Row", "Truck", "Date", "Liters"]], use_container_width=True, hide_index=True)
            else:
                st.success("🚀 Successfully Added: 0 transactions!")

            # Skipped Section
            if skipped_records:
                st.warning(f"ℹ️ Skipped (Already Exists): {len(skipped_records)} transactions")
                with st.expander("👉 View Skipped Duplicates", expanded=False):
                    st.dataframe(pd.DataFrame(skipped_records), use_container_width=True, hide_index=True)

            # Error Section with Highlighting
            if error_records:
                st.error(f"🚨 Formatting Errors Found: {len(error_records)} rows skipped!")
                err_df = pd.DataFrame(error_records)

                def highlight_errors(row):
                    styles = [''] * len(row)
                    failed = row['failed_fields']
                    if "Truck" in failed:
                        styles[err_df.columns.get_loc('Truck')] = 'background-color: #ffb3b3; color: black; font-weight: bold;'
                    if "Date" in failed:
                        styles[err_df.columns.get_loc('Date')] = 'background-color: #ffb3b3; color: black; font-weight: bold;'
                    if "Liters" in failed:
                        styles[err_df.columns.get_loc('Liters')] = 'background-color: #ffb3b3; color: black; font-weight: bold;'
                    return styles

                with st.expander("❌ View Formatting Errors (Errors Highlighted in Pink)", expanded=True):
                    st.dataframe(
                        err_df.style.apply(highlight_errors, axis=1).subset(["Excel Row", "Truck", "Date", "Liters", "Reason/Error"]),
                        use_container_width=True,
                        hide_index=True
                    )
            
        except Exception as e:
            st.error(f"An error occurred while processing the file: {str(e)}")