import json

import streamlit as st


def record_event(conn, action, module, entity_type=None, entity_id=None, description="",
                 old_values=None, new_values=None, status="SUCCESS", severity="INFO",
                 location=None, commit=True):
    """Write a structured, append-only audit event."""
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO audit_events
           (user_id, username, user_role, action, module, entity_type, entity_id,
            description, old_values, new_values, status, severity, business_location)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s)""",
        (
            st.session_state.get("user_id"), st.session_state.get("user", "System"),
            st.session_state.get("role", "SYSTEM"), action, module, entity_type,
            str(entity_id) if entity_id is not None else None, description,
            json.dumps(old_values) if old_values is not None else None,
            json.dumps(new_values) if new_values is not None else None,
            status, severity, location,
        ),
    )
    if commit:
        conn.commit()

