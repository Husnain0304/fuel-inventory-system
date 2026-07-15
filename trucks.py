import streamlit as st
import pandas as pd
from datetime import datetime

# Helper to write to audit log automatically
def log_action(cursor, conn, action_text):
    current_user = st.session_state.get("user", "System Admin")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        'INSERT INTO audit_log ("user", action, timestamp) VALUES (%s, %s, %s)',
        (current_user, action_text, timestamp)
    )
    conn.commit()

def render_trucks(conn, cursor):

    st.title("🚛 Manage Trucks")

    # =============================
    # ADD TRUCK SECTION
    # =============================

    col1, col2, col3 = st.columns(3)

    emirate = col1.selectbox("Emirate", ["DXB","AUH","SHJ","AJM","RAK","FUJ","UAQ"])
    plate_code = col2.text_input("Plate Code")
    plate_number = col3.text_input("Plate Number")

    selling_price = st.number_input(
        "Custom Selling Price per Liter (Optional)",
        min_value=0.0,
        format="%.2f",
        value=0.0
    )

    if st.button("Add Truck"):
        try:
            cursor.execute(
                "INSERT INTO trucks (emirate, plate_code, plate_number, selling_price_per_liter) VALUES (%s, %s, %s, %s)",
                (
                    emirate,
                    plate_code.upper(),
                    plate_number,
                    selling_price if selling_price > 0 else None
                )
            )
            # Log the addition
            truck_label = f"{emirate} {plate_code.upper()} {plate_number}"
            log_action(cursor, conn, f"ADDED TRUCK: {truck_label} (Selling Price: {selling_price if selling_price > 0 else 'Global Price'})")
            
            conn.commit()
            st.success("Truck added ✅")
            st.rerun()
        except Exception as e:
            st.error("Truck already exists or a database error occurred.")

    st.markdown("---")

    # =============================
    # LIST TRUCKS
    # =============================

    st.subheader("Registered Trucks")

    trucks_df = pd.read_sql_query(
        "SELECT id, emirate, plate_code, plate_number, selling_price_per_liter FROM trucks",
        conn
    )

    if trucks_df.empty:
        st.info("No trucks available.")
        return

    for _, row in trucks_df.iterrows():
        truck_id = row["id"]
        full_name = f"{row['emirate']} {row['plate_code']} {row['plate_number']}"

        c1, c2, c3 = st.columns([4, 2, 1])

        c1.write(full_name)

        if row["selling_price_per_liter"] is not None:
            c2.write(f"Custom Price: {row['selling_price_per_liter']:,.2f}")
        else:
            c2.write("Using Global Price")

        # Instead of deleting instantly, clicking this button now triggers the warning pop-up
        if c3.button("Delete", key=f"delete_btn_{truck_id}"):
            st.session_state[f"show_confirm_del_{truck_id}"] = True
            st.rerun()

        # --- SAFETY CONFIRMATION DIALOG (Appears directly below the selected row) ---
        if st.session_state.get(f"show_confirm_del_{truck_id}", False):
            with st.container(border=True):
                st.error(f"⚠️ **CONFIRM TRUCK DELETION**")
                st.write(f"Are you sure you want to permanently delete truck **{full_name}**?")
                st.write("🔴 **Important:** This will also delete all transactions history connected to this truck!")
                
                # Checkbox to make sure they are paying attention
                confirm_checkbox = st.checkbox(
                    "I verify that I want to delete this truck and lose its transaction history.",
                    key=f"check_auth_delete_{truck_id}"
                )

                col_btn1, col_btn2 = st.columns(2)
                
                if col_btn1.button("Yes, Delete Permanently", key=f"yes_del_{truck_id}", type="primary"):
                    if not confirm_checkbox:
                        st.error("Please check the confirmation box first!")
                    else:
                        # 1. Delete associated transactions to keep database happy using Postgres '%s' syntax
                        cursor.execute("DELETE FROM transactions WHERE truck_id = %s", (truck_id,))
                        
                        # 2. Delete the truck itself using Postgres '%s' syntax
                        cursor.execute("DELETE FROM trucks WHERE id=%s", (truck_id,))
                        
                        # 3. Log the entire delete action with details
                        log_action(cursor, conn, f"DELETED TRUCK & HISTORY: Removed truck '{full_name}' and all associated transactions.")
                        
                        conn.commit()
                        
                        # Cleanup screen states
                        st.session_state[f"show_confirm_del_{truck_id}"] = False
                        st.success(f"Truck {full_name} has been deleted.")
                        st.rerun()

                if col_btn2.button("Cancel", key=f"cancel_del_{truck_id}"):
                    st.session_state[f"show_confirm_del_{truck_id}"] = False
                    st.rerun()
