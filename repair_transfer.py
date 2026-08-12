import streamlit as st


DESTINATION_TRANSACTION_ID = 99
TRANSFER_LITERS = 631.0

SOURCE_EMIRATE = "SHJ"
SOURCE_PLATE_CODE = "1"
SOURCE_PLATE_NUMBER = "67814"

DESTINATION_EMIRATE = "DXB"
DESTINATION_PLATE_CODE = "D"
DESTINATION_PLATE_NUMBER = "24631"


def render_transfer_repair(conn):
    if st.session_state.get("role") != "ADMIN":
        return

    st.error(
        "Historical transfer repair: TX-99 contains the destination IN record, "
        "but its matching source OUT record is missing."
    )

    confirmation = st.checkbox(
        "I confirm the historical transfer was 631 L from "
        "SHJ 1 67814 to DXB D 24631.",
        key="confirm_tx99_repair",
    )

    if st.button(
        "Repair missing TX-99 transfer OUT",
        type="primary",
        disabled=not confirmation,
    ):
        cursor = conn.cursor()

        try:
            # Lock and verify the existing destination transaction.
            cursor.execute(
                """
                SELECT
                    tx.id,
                    tx.truck_id,
                    tx.date,
                    tx.liters,
                    tx.type,
                    tx.transfer_partner_id,
                    tr.emirate,
                    tr.plate_code,
                    tr.plate_number
                FROM transactions tx
                JOIN trucks tr ON tr.id = tx.truck_id
                WHERE tx.id = %s
                FOR UPDATE
                """,
                (DESTINATION_TRANSACTION_ID,),
            )

            destination = cursor.fetchone()

            if not destination:
                raise ValueError("TX-99 was not found. Nothing was changed.")

            (
                transaction_id,
                destination_truck_id,
                transfer_date,
                liters,
                transaction_type,
                existing_partner_id,
                emirate,
                plate_code,
                plate_number,
            ) = destination

            if transaction_type != "IN":
                raise ValueError(
                    "TX-99 is not an IN transaction. Nothing was changed."
                )

            if abs(float(liters) - TRANSFER_LITERS) > 0.001:
                raise ValueError(
                    f"TX-99 contains {liters} L instead of 631 L. "
                    "Nothing was changed."
                )

            if (
                str(emirate).upper() != DESTINATION_EMIRATE
                or str(plate_code).upper() != DESTINATION_PLATE_CODE
                or str(plate_number) != DESTINATION_PLATE_NUMBER
            ):
                raise ValueError(
                    "TX-99 does not belong to DXB D 24631. "
                    "Nothing was changed."
                )

            if existing_partner_id:
                raise ValueError(
                    f"TX-99 is already linked to TX-{existing_partner_id}. "
                    "The repair was not run again."
                )

            # Find the source truck.
            cursor.execute(
                """
                SELECT id
                FROM trucks
                WHERE UPPER(emirate) = %s
                  AND UPPER(plate_code) = %s
                  AND plate_number = %s
                """,
                (
                    SOURCE_EMIRATE,
                    SOURCE_PLATE_CODE,
                    SOURCE_PLATE_NUMBER,
                ),
            )

            source = cursor.fetchone()

            if not source:
                raise ValueError(
                    "Source truck SHJ 1 67814 was not found. "
                    "Nothing was changed."
                )

            source_truck_id = source[0]

            # Create only the missing OUT side.
            cursor.execute(
                """
                INSERT INTO transactions (
                    truck_id,
                    date,
                    liters,
                    type,
                    transfer_partner_id,
                    created_by
                )
                VALUES (%s, %s, %s, 'OUT', %s, %s)
                RETURNING id
                """,
                (
                    source_truck_id,
                    transfer_date,
                    TRANSFER_LITERS,
                    DESTINATION_TRANSACTION_ID,
                    st.session_state.get("user", "admin"),
                ),
            )

            source_transaction_id = cursor.fetchone()[0]

            # Link TX-99 back to the newly created OUT record.
            cursor.execute(
                """
                UPDATE transactions
                SET transfer_partner_id = %s
                WHERE id = %s
                  AND transfer_partner_id IS NULL
                """,
                (
                    source_transaction_id,
                    DESTINATION_TRANSACTION_ID,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "TX-99 changed during the repair. Nothing was committed."
                )

            cursor.execute(
                """
                INSERT INTO audit_log ("user", action, timestamp)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                """,
                (
                    st.session_state.get("user", "admin"),
                    (
                        "REPAIRED historical transfer TX-99: "
                        f"created missing 631 L OUT transaction "
                        f"TX-{source_transaction_id} for SHJ 1 67814"
                    ),
                ),
            )

            conn.commit()

            st.success(
                f"Repair completed. TX-99 is now linked to "
                f"TX-{source_transaction_id}. "
                "No additional fuel was added to DXB D 24631."
            )

        except Exception as error:
            conn.rollback()
            st.error(str(error))
