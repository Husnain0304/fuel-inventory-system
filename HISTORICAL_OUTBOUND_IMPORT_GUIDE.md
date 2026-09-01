# Historical Outbound Delivery Import

Use **Integration Inbox** to upload an Excel file containing old and new outbound truck deliveries.

## Required Excel columns

- `date`
- `truck`
- `liters`
- `ticket_number` (recommended, but older rows may be blank)

Download the template from the page if your spreadsheet uses different headings.

## What each result means

- **NEW** — no matching transaction exists. It can be posted and will reduce the truck inventory.
- **MATCHED** — the delivery already exists. It will be skipped and inventory will not change.
- **ENRICH** — the delivery already exists but its ticket number is blank. Only the missing ticket number will be added; inventory will not change.
- **CONFLICT** — the ticket number already belongs to different transaction details. Nothing can be posted until corrected.
- **AMBIGUOUS** — more than one old transaction could match the row. Review it manually.
- **FILE DUPLICATE** — the uploaded spreadsheet contains a repeated row or ticket.
- **INSUFFICIENT STOCK** — posting the new outbound row would make the truck balance negative.
- **CLOSED PERIOD** — the transaction date is in a locked inventory period.
- **INVALID** — a required value is missing or incorrect.

## Safe test

1. Open **Integration Inbox** and download the template.
2. Add one delivery that already exists with the same date, truck, liters and ticket. Analyse it; it should show **MATCHED**.
3. Add one existing delivery whose database ticket is blank, then provide its ticket in Excel. It should show **ENRICH** and must not change stock.
4. Add one genuinely new delivery. It should show **NEW**.
5. Download the reconciliation report before posting.
6. Confirm and post only when there are no blocked rows.
7. Open **Truck Ledger** and verify the new delivery appears once and the truck balance reduced once.
8. Upload the same file again. All posted rows should now show **MATCHED**, with no additional stock reduction.

The importer never overwrites the truck, date or liters of an existing transaction. It only fills a blank ticket number when the inventory details identify one unique matching record.
