from pathlib import Path

import streamlit as st


DEFAULT_PROFILE = {
    "company_name": "FILLIT",
    "application_name": "Fuel Inventory Control",
    "tagline": "Inventory intelligence for fuel operations",
    "primary_color": "#8C1C1C",
    "secondary_color": "#171717",
    "accent_color": "#05AF52",
    "currency": "AED",
    "timezone": "Asia/Dubai",
    "date_format": "DD MMM YYYY",
    "volume_unit": "L",
    "logo_path": "assets/fillit-logo.png",
    "report_footer": "Confidential inventory report",
}


def get_company_profile(conn):
    profile = DEFAULT_PROFILE.copy()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT company_name, application_name, tagline, primary_color,
                  secondary_color, accent_color, currency, timezone,
                  date_format, volume_unit, logo_path, report_footer
           FROM company_profile ORDER BY id LIMIT 1"""
    )
    row = cursor.fetchone()
    if row:
        for key, value in zip(profile.keys(), row):
            if value not in (None, ""):
                profile[key] = value
    return profile


def logo_file(profile):
    path = Path(__file__).parent / profile.get("logo_path", "")
    return path if path.is_file() else None


def save_company_profile(conn, values, user="System"):
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE company_profile SET
           company_name=%s, application_name=%s, tagline=%s,
           primary_color=%s, secondary_color=%s, accent_color=%s,
           currency=%s, timezone=%s, date_format=%s, volume_unit=%s,
           report_footer=%s, updated_at=CURRENT_TIMESTAMP, updated_by=%s
           WHERE id=(SELECT id FROM company_profile ORDER BY id LIMIT 1)""",
        (
            values["company_name"], values["application_name"], values["tagline"],
            values["primary_color"], values["secondary_color"], values["accent_color"],
            values["currency"], values["timezone"], values["date_format"],
            values["volume_unit"], values["report_footer"], user,
        ),
    )
    conn.commit()
    st.session_state["company_profile"] = values
