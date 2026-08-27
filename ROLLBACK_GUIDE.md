# Rollback Guide

1. Keep the database unchanged; this release uses additive tables and columns.
2. Revert the complete-release GitHub commit, or upload every file from the supplied rollback ZIP.
3. Confirm Streamlit still points to the same branch and `app.py`.
4. Reboot once and sign in.
5. Verify Command Centre, Fuel Operations, Fleet Inventory and existing reports.

Do not delete new database tables manually. Retaining them preserves evidence created during testing and does not prevent the older application from running.
