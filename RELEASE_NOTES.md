# Complete Inventory Release

## Scope

This is the consolidated Foundation V2 inventory release. It manages fuel inventory only. Delivery dispatch, customer workflow, route planning and driver operations are deliberately excluded.

## New and consolidated capabilities

- Professional Command Centre and persistent one-click navigation.
- Truck, depot, tank, product and supplier master controls.
- Supplier bookings, releases, receipts, claims, invoice matching and landed cost.
- Product batches, quality inspection, quarantine/release and FEFO aging.
- Tank-to-truck, truck-to-truck and depot/tank stock-in-transit controls.
- Truck and tank physical counts with review and controlled adjustment.
- Calibration register and inventory incident investigation/closure.
- Internal stock commitments, forecasting and available inventory.
- Moving weighted-average valuation and month-end inventory close.
- Approval thresholds, notifications, evidence, audit, health checks and master reports.

## Safety and reliability

- Permanent transaction deletion has been removed; corrections use controlled reversal/change requests.
- Imported transaction evidence cannot be edited or erased in the import screen.
- Accounts are deactivated and their sessions revoked instead of deleting identity history.
- Database initialization is cached once per app process and stale connections reconnect automatically.
- All schema changes are additive and idempotent.
- Role-based workspaces and action guards separate entry, review and approval duties.

## Upgrade behavior

Existing inventory and history remain in place. New tables and columns are created automatically on first start. Use the test branch, database backup, acceptance test and rollback package supplied with the release.
