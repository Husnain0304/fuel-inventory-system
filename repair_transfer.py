import streamlit as st


DESTINATION_TRANSACTION_ID = 99
BROKEN_PARTNER_ID = 98
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
        "Confirmed database issue: TX-99 is a 631 L IN record for "
        "DXB D 24631, but its linked OUT record TX-98 was deleted."
    )

    confirmation = st.checkbox(
        "I confirm that the missing transaction must remove 631 L "
        "from SHJ 1 67814 without adding any more fuel to DXB D 24631.",
        key="confirm_final_tx99_repair",
    )

    if st.button(
        "Create missing 631 L OUT and repair TX-99",
        type="primary",
        disabled=not confirmation,
    ):
        cursor = conn.cursor()

        try:
            # Lock and verify TX-99.
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
                JOIN trucks tr
                    ON tr.id = tx.truck_id
                WHERE tx.id = %s
                FOR UPDATE
                """,
                (DESTINATION_TRANSACTION_ID,),
            )

            destination = cursor.fetchone()

            if not destination:
                raise ValueError(
                    "TX-99 was not found. Nothing was changed."
                )

            (
                transaction_id,
                destination_truck_id,
                transfer_date,
                liters,
                transaction_type,
                partner_id,
                destination_emirate,
                destination_plate_code,
                destination_plate_number,
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
                str(destination_emirate).upper()
                != DESTINATION_EMIRATE
                or str(destination_plate_code).upper()
                != DESTINATION_PLATE_CODE
                or str(destination_plate_number)
                != DESTINATION_PLATE_NUMBER
            ):
                raise ValueError(
                    "TX-99 does not belong to DXB D 24631. "
                    "Nothing was changed."
                )

            if partner_id != BROKEN_PARTNER_ID:
                raise ValueError(
                    f"TX-99 now points to TX-{partner_id}, not TX-98. "
                    "The database changed and nothing was repaired."
                )

            # Confirm that broken partner TX-98 is genuinely absent.
            cursor.execute(
                """
                SELECT id
                FROM transactions
                WHERE id = %s
                """,
                (BROKEN_PARTNER_ID,),
            )

            if cursor.fetchone():
                raise ValueError(
                    "TX-98 now exists. Nothing was changed."
                )

            # Locate and lock SHJ 1 67814.
            cursor.execute(
                """
                SELECT id
                FROM trucks
                WHERE UPPER(emirate) = %s
                  AND UPPER(plate_code) = %s
                  AND plate_number = %s
                FOR UPDATE
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

            # Make sure an equivalent OUT was not already recreated.
            cursor.execute(
                """
                SELECT id, transfer_partner_id
                FROM transactions
                WHERE truck_id = %s
                  AND date = %s
                  AND type = 'OUT'
                  AND ABS(liters - %s) < 0.001
                FOR UPDATE
                """,
                (
                    source_truck_id,
                    transfer_date,
                    TRANSFER_LITERS,
                ),
            )

            existing_out = cursor.fetchone()

            if existing_out:
                raise ValueError(
                    f"A 631 L OUT transaction TX-{existing_out[0]} "
                    "already exists for SHJ 1 67814 on this date. "
                    "Nothing was changed."
                )

            # Create only the missing OUT transaction.
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

            new_out_id = cursor.fetchone()[0]

            # Replace broken TX-98 reference with the new OUT record.
            cursor.execute(
                """
                UPDATE transactions
                SET transfer_partner_id = %s
                WHERE id = %s
                  AND transfer_partner_id = %s
                """,
                (
                    new_out_id,
                    DESTINATION_TRANSACTION_ID,
                    BROKEN_PARTNER_ID,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "TX-99 changed during repair. "
                    "Nothing was committed."
                )

            cursor.execute(
                """
                INSERT INTO audit_log (
                    "user",
                    action,
                    timestamp
                )
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                """,
                (
                    st.session_state.get("user", "admin"),
                    (
                        "REPAIRED TX-99 broken transfer: created "
                        f"TX-{new_out_id} as 631 L OUT for "
                        "SHJ 1 67814 and replaced deleted TX-98 link"
                    ),
                ),
            )

            conn.commit()

            st.success(
                f"Repair completed. TX-{new_out_id} was created as "
                "the missing 631 L OUT for SHJ 1 67814. "
                f"TX-99 is now linked to TX-{new_out_id}. "
                "No additional fuel was added to DXB D 24631."
            )

        except Exception as error:
            conn.rollback()
            st.error(str(error))
