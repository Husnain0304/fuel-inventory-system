import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlsplit, urlunsplit

import streamlit as st


def _email_settings():
    try:
        return dict(st.secrets.get("email", {}))
    except Exception:
        return {}


def clean_app_url():
    settings = _email_settings()
    configured = str(settings.get("app_url", "")).strip()
    if configured:
        return configured.rstrip("/")
    try:
        current = str(st.context.url)
        parts = urlsplit(current)
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    except Exception:
        return ""


def email_is_configured():
    settings = _email_settings()
    return all(str(settings.get(key, "")).strip() for key in ("host", "username", "password", "from_email"))


def send_user_invitation(recipient, username, temporary_password, role_label, company_name, application_name):
    settings = _email_settings()
    if not email_is_configured():
        return False, "Email delivery is not configured in Streamlit Secrets."
    app_url = clean_app_url()
    message = EmailMessage()
    message["Subject"] = f"Your {application_name} account"
    message["From"] = settings["from_email"]
    message["To"] = recipient
    message.set_content(
        f"Hello,\n\nAn account has been created for you in {application_name}.\n\n"
        f"Company: {company_name}\nUsername: {username}\nTemporary password: {temporary_password}\n"
        f"Role: {role_label}\nSign-in link: {app_url}\n\n"
        "You must create a new private password immediately after signing in. "
        "Do not forward this email or share the temporary password.\n"
    )
    port = int(settings.get("port", 587))
    use_ssl = str(settings.get("use_ssl", "false")).lower() in ("true", "1", "yes")
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(settings["host"], port, context=ssl.create_default_context(), timeout=20) as server:
                server.login(settings["username"], settings["password"])
                server.send_message(message)
        else:
            with smtplib.SMTP(settings["host"], port, timeout=20) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(settings["username"], settings["password"])
                server.send_message(message)
        return True, "Invitation email sent successfully."
    except Exception as error:
        return False, f"Email could not be sent: {error}"
