# Professional Fuel Inventory Control

A complete, configurable fuel inventory management system for truck stock, depots, tanks, supplier procurement, product quality, controlled movements, reconciliation, valuation, forecasting, evidence, approvals and audit reporting.

This release is intentionally limited to **inventory management**. Customer orders, route planning, dispatch execution, driver workflow and delivery operations belong in a separate future platform and are not part of this application.

## Main controls

- Command Centre with inventory position, exceptions and one-click workspaces.
- Truck inventory and complete truck ledger.
- Multi-depot and multi-tank master data, capacity, minimum and reorder controls.
- Tank receipts, issues, transfers, stock in transit and destination receipt variance.
- Supplier master, bookings, releases, receipt consumption, claims and landed costing.
- Product specifications, batches, quality inspections, quarantine/release and FEFO.
- Physical truck and tank counts with independent review and controlled adjustments.
- Calibration, loss/gain/spill/contamination incidents and formal closure.
- Internal stock commitments and available-to-promise visibility.
- Forecasting, financial valuation, month-end close and inventory-health diagnostics.
- Evidence Centre, notifications, approval limits, audit timeline and downloadable reports.
- Role-based access, persistent login sessions and non-destructive correction/reversal controls.

## Safe deployment

1. Back up the current Neon database and keep the rollback ZIP supplied with this release.
2. Upload every file and folder from the complete release ZIP to one GitHub branch.
3. In Streamlit Community Cloud, deploy `app.py` and select Python 3.12.
4. Open the app's **Secrets** settings and add:

```toml
[connections.postgresql]
url = "YOUR_NEON_POSTGRESQL_CONNECTION_URL"

[bootstrap]
username = "YOUR_FIRST_ADMIN_USERNAME"
password = "A_LONG_UNIQUE_PASSWORD"
```

5. Reboot once, sign in, open **Inventory Health**, then follow `END_TO_END_TEST_GUIDE.md`.

The bootstrap credentials are used only if the users table is empty. All database upgrades are additive and run automatically; the application never resets or erases existing inventory.

## Free components

The application uses Streamlit, PostgreSQL/Neon, pandas, Plotly, bcrypt and openpyxl. Free tiers are suitable for demonstration and light use, subject to provider limits.
