import pandas as pd
import streamlit as st


def render_transfer_repair(conn):
    if st.session_state.get("role") != "ADMIN":
        return

    st.warning(
        "Diagnostic inspection only. This section does not change, "
        "create or delete any transactions."
    )

    if st.button(
        "Inspect TX-98 and TX-99 directly",
        use_container_width=True,
    ):
        cursor = conn.cursor()

        try:
            # Read transactions directly without requiring a matching truck.
            cursor.execute(
                """
                SELECT
                    id,
                    truck_id,
                    date,
                    liters,
                    type,
                    transfer_partner_id,
                    created_by
                FROM transactions
                WHERE id IN (98, 99)
                ORDER BY id
                """
            )

            transaction_rows = cursor.fetchall()

            transaction_df = pd.DataFrame(
                transaction_rows,
                columns=[
                    "Transaction ID",
                    "Truck ID",
                    "Date",
                    "Liters",
                    "Type",
                    "Partner Transaction ID",
                    "Created By",
                ],
            )

            st.subheader("Direct transaction records")

            if transaction_df.empty:
                st.error(
                    "Neither TX-98 nor TX-99 exists in the "
                    "transactions table."
                )
            else:
                st.dataframe(
                    transaction_df,
                    use_container_width=True,
                    hide_index=True,
                )

            # Inspect the truck records referenced by these transactions.
            cursor.execute(
                """
                SELECT
                    tx.id AS transaction_id,
                    tx.truck_id,
                    tr.emirate,
                    tr.plate_code,
                    tr.plate_number
                FROM transactions tx
                LEFT JOIN trucks tr
                    ON tr.id = tx.truck_id
                WHERE tx.id IN (98, 99)
                ORDER BY tx.id
                """
            )

            truck_rows = cursor.fetchall()

            truck_df = pd.DataFrame(
                truck_rows,
                columns=[
                    "Transaction ID",
                    "Truck ID",
                    "Emirate",
                    "Plate Code",
                    "Plate Number",
                ],
            )

            st.subheader("Referenced truck records")

            st.dataframe(
                truck_df,
                use_container_width=True,
                hide_index=True,
            )

            # Explain what was found.
            found_ids = set()

            if not transaction_df.empty:
                found_ids = set(
                    transaction_df["Transaction ID"].astype(int)
                )

            if 98 in found_ids and 99 in found_ids:
                st.success(
                    "Both TX-98 and TX-99 exist in the database. "
                    "Review their truck, quantity, type and partner fields."
                )

            elif 99 in found_ids and 98 not in found_ids:
                st.error(
                    "TX-99 exists, but TX-98 has been deleted. "
                    "TX-99 contains a broken partner reference."
                )

            elif 98 in found_ids and 99 not in found_ids:
                st.error(
                    "TX-98 exists, but TX-99 has been deleted."
                )

            # Detect a hidden transaction caused by a missing truck.
            if not truck_df.empty:
                hidden_rows = truck_df[
                    truck_df["Emirate"].isna()
                ]

                if not hidden_rows.empty:
                    hidden_ids = ", ".join(
                        f"TX-{int(value)}"
                        for value in hidden_rows[
                            "Transaction ID"
                        ].tolist()
                    )

                    st.error(
                        f"{hidden_ids} exists, but its truck record "
                        "is missing. The normal history screen hides it "
                        "because it uses an inner database join."
                    )

        except Exception as error:
            conn.rollback()
            st.error(
                f"Inspection failed: {error}"
            )
