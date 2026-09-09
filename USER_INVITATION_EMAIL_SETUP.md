# User invitation email setup

The application can create a user, generate a temporary password and email the sign-in details. The recipient must choose a new private password immediately after signing in.

## Configure Streamlit Secrets

Open the app in Streamlit Community Cloud, choose **Settings**, open **Secrets**, and add the following configuration. Never add these values to GitHub.

```toml
[email]
host = "smtp.gmail.com"
port = 587
username = "your-sender@gmail.com"
password = "your-google-app-password"
from_email = "your-sender@gmail.com"
use_ssl = false
app_url = "https://your-app-name.streamlit.app"
```

For Gmail, use a Google App Password rather than the normal Gmail password. Two-step verification must be enabled on the sender Google account before an App Password can be created.

For another email provider, replace the host, port, username and password with the SMTP information supplied by that provider. If the provider requires SSL from the beginning, normally on port 465, set `use_ssl = true`.

Save the secrets and allow Streamlit to restart the app.

## Create and invite a user

1. Open **User Access**.
2. Open **Create and invite a new user**.
3. Enter the username, email address, phone number and role.
4. Select **Create account and send invitation**.
5. The application generates a strong temporary password and emails it with the clean application URL.
6. The recipient signs in and is required to create a new private password before the dashboard opens.

If email is not configured or delivery fails, the account is still created and the invitation details are displayed to the administrator for secure manual sharing.

## Reset a user's password

Select the account in **User Access**, open **Issue a new temporary password**, confirm the action and send it. Existing sessions for that user are revoked, and the replacement temporary password must be changed after the next login.
