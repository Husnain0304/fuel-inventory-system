# End-to-End Acceptance Test

Perform this on the test branch and test database. Use small, clearly identifiable quantities and keep the reports.

## 1. Access and reliability

- Sign in, refresh and confirm you remain signed in.
- Open five pages; each must open on the first click.
- Use **Home · Command Centre** and confirm it returns immediately.
- Sign out and confirm protected pages are inaccessible.

## 2. Master data

- Verify a product and quality specification.
- Verify a supplier and its approved product.
- Create a depot and two compatible tanks with capacity, safe capacity, minimum, reorder and dead-stock levels.
- Create a truck with product, capacity, minimum, reorder and status.

## 3. Supplier receipt and quality

- Create a supplier booking and release.
- Receive tank stock with ordered, dispatched and accepted litres.
- Confirm booking consumption and any shortage claim.
- Confirm a batch exists, inspect it and release it.
- Register and approve an invoice match.
- Confirm Financial Valuation uses landed cost without changing quantity.

## 4. Movements

- Issue tank stock to a truck; confirm tank decreases and truck increases once.
- Transfer between trucks; confirm linked OUT/IN records and balances.
- Plan a tank transfer; confirm no stock change while PLANNED.
- Dispatch; confirm source decreases and transit increases.
- Receive; confirm destination increases and variance is recorded.
- Cancel another plan; confirm no stock change.

## 5. Counts and incidents

- Submit and approve a truck count adjustment.
- Submit, review and post a tank count adjustment with a different authorized user (or documented Admin override).
- Register a calibration.
- Open and close an incident with root cause, corrective action and evidence.

## 6. Governance

- Trigger an approval limit and confirm the request remains pending.
- Verify submission confirmation and status under Notifications/My Requests.
- Approve/reject and verify the requester notification.
- Request a correction/reversal and confirm permanent deletion is unavailable.
- Upload, open, download and archive evidence.
- Verify Audit Centre shows user, time, action, record and description.

## 7. Close, health and reports

- Resolve every Critical Inventory Health finding.
- Confirm Month-End Closing is blocked by a pending item, resolve it, and download the certificate.
- Download Inventory, Movement, Procurement, Quality, Transit, Counts, Incidents, Valuation and Audit reports.
- Open every workbook and verify headings, dates and quantities.

Promote only with no application errors, unexplained differences, missing audit events or broken downloads.
