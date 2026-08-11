# FILLIT Professional v2

FILLIT is a Streamlit application for fleet fuel inventory, uplifts, deliveries,
internal transfers, truck ledgers, approvals, reporting, and audit history.

## What changed in this edition

- Branded FILLIT navigation, login screen, theme, logo, and clearer page headers.
- Official FILLIT logo and burgundy/black corporate visual system based on fillit.co.
- Rebuilt executive dashboard with exceptions, live inventory, operational trends,
  recent activity, and a compact reporting hierarchy.
- Automatic database reconnection after Neon or Streamlit closes an idle session.
- Database-verified roles; user and role values are never trusted from the URL.
- bcrypt password hashing with automatic upgrade of legacy SHA-256 accounts.
- Login attempt throttling and stronger password rules.
- Admin-only protection for settings and user management.
- Centralized, cached database initialization and compatibility migrations.
- Database indexes for truck history, date filters, audit logs, and approvals.
- Bounded audit views so large histories do not freeze the interface.
- Example secrets file with no live credentials.

## Deploy on Streamlit Community Cloud

1. Create a new private GitHub repository or a new branch. Do not overwrite the
   working production version until this edition has been tested.
2. Upload every file and folder in this project.
3. In Streamlit Community Cloud, choose `app.py` as the main file.
4. Open the app's **Secrets** settings and add:

```toml
[connections.postgresql]
url = "YOUR_NEON_POSTGRESQL_CONNECTION_URL"

[bootstrap]
username = "YOUR_FIRST_ADMIN_USERNAME"
password = "A_LONG_UNIQUE_PASSWORD"
```

The bootstrap credentials are used only if the `users` table is empty. After
the first admin exists, create named accounts in **User Access**.

## Important upgrade notes

- Back up the Neon database before the first deployment.
- Existing SHA-256 accounts remain usable. Their password is upgraded to bcrypt
  automatically when the user signs in successfully.
- Remove the old `admin/admin123` account or change its password immediately.
- Keep `.streamlit/secrets.toml` out of GitHub. Only the example file belongs in
  the repository.
- Test uploads, transfers, approvals, deletes, reports, and exports on a copy of
  the database before replacing the current live app.

## Local requirements

Install the packages in `requirements.txt`, copy
`.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`, fill in your own
private values, then run:

```text
streamlit run app.py
```

## Free components

This edition uses Streamlit, Neon PostgreSQL, pandas, Plotly, bcrypt, and
openpyxl. All have free/open-source options suitable for the current project,
subject to the usage limits of the hosting providers.
