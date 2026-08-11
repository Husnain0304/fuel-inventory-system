import streamlit as st
import pandas as pd

def render_approvals(conn, cursor):

    if st.session_state["role"] != "ADMIN":
        st.warning("Only Admin can approve refills")
        st.stop()

    st.title("✅ Refill Approvals")

    requests_df = pd.read_sql_query("""
        SELECT rr.id,
               rr.truck_id,
               trucks.emirate || ' ' || trucks.plate_code || ' ' || trucks.plate_number AS truck,
               rr.requested_liters,
               rr.status,
               rr.requested_by,
               rr.timestamp
        FROM refill_requests rr
        JOIN trucks ON rr.truck_id = trucks.id
        WHERE rr.status = 'PENDING'
        ORDER BY rr.id DESC
    """, conn)

    if requests_df.empty:
        st.info("No pending refill requests")
        return

    for _, row in requests_df.iterrows():

        col1, col2, col3 = st.columns([4,1,1])

        col1.write(
            f"{row['truck']} → {row['requested_liters']:,.2f} L "
            f"(Requested by {row['requested_by']})"
        )

        if col2.button("Approve", key=f"approve_{row['id']}"):
            cursor.execute(
                "INSERT INTO transactions (truck_id, date, liters, type) VALUES (?, DATE('now'), ?, 'IN')",
                (row["truck_id"], row["requested_liters"])
            )

            cursor.execute(
                "UPDATE refill_requests SET status='APPROVED' WHERE id=?",
                (row["id"],)
            )

            cursor.execute(
                "INSERT INTO audit_log (user, action, timestamp) VALUES (?, ?, datetime('now'))",
                (
                    st.session_state["user"],
                    f"Approved refill for {row['truck']} ({row['requested_liters']} L)"
                )
            )

            conn.commit()
            st.success("Refill approved ✅")
            st.rerun()

        if col3.button("Reject", key=f"reject_{row['id']}"):
            cursor.execute(
                "UPDATE refill_requests SET status='REJECTED' WHERE id=?",
                (row["id"],)
            )

            cursor.execute(
                "INSERT INTO audit_log (user, action, timestamp) VALUES (?, ?, datetime('now'))",
                (
                    st.session_state["user"],
                    f"Rejected refill for {row['truck']} ({row['requested_liters']} L)"
                )
            )

            conn.commit()
            st.warning("Refill rejected ❌")
            st.rerun()