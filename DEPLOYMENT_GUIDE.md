# One-Time Deployment Guide

## Before uploading

1. Download a backup from Neon or create a database branch/restore point.
2. Download the current GitHub branch as a ZIP and keep it unchanged.
3. Use the supplied complete release ZIP. Do not mix individual files from older releases.

## Replace the GitHub branch

1. Open the test branch used by the Streamlit test app.
2. Remove the old application files from that branch, but keep `.streamlit/secrets.toml` out of GitHub.
3. Extract the complete release ZIP on your computer.
4. In GitHub choose **Add file → Upload files** and upload all extracted files and folders together.
5. Confirm `inventory_health.py`, `storage_control.py`, `stock_transit.py`, `receipt_costing.py`, and `schema_bootstrap.py` are visible.
6. Commit with the message `Complete inventory management release`.

## Streamlit Cloud

1. Open the deployed test app from Streamlit Community Cloud.
2. Verify repository, branch and main file (`app.py`) are correct.
3. In Advanced settings choose Python 3.12.
4. Confirm the PostgreSQL URL still exists in Secrets.
5. Reboot once. The first opening can take longer while additive database controls are created.
6. Do not repeatedly reboot. If the page is still blank after five minutes, inspect the newest log line first.

Promote to the main branch only after every test in `END_TO_END_TEST_GUIDE.md` passes.
