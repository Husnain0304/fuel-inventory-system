# Premium Interface Acceptance Test

## Confirm the new release

The sidebar must show collapsible groups named Stock Operations, Storage Network, Supply & Quality, Planning & Finance, Control & Assurance and Administration. The Command Centre must show **Inventory Control Room** and **Workflow Launcher**.

## Desktop check

1. Open the Command Centre and confirm the dark control-room hero and white session panel appear side by side.
2. Expand each permitted sidebar group and open at least one page. Every page must open on the first click and the active page must be highlighted.
3. Use all four Workflow Launcher dropdowns. Only workspaces allowed for the signed-in role should appear.
4. Open Fuel Operations, Storage Operations, Supplier Procurement, Product & Quality, Inventory Health and Report Centre.
5. Confirm headers, forms, tabs, metrics, tables, alerts and buttons share the same design language.
6. Use Home/Command Centre and refresh the browser. The selected page and login must remain stable.

## Responsive check

1. Reduce the browser width or use a laptop-sized window.
2. Confirm the sidebar remains usable, page headers stack cleanly and no important button is cut off.
3. Collapse the Streamlit sidebar and confirm the content expands without horizontal page scrolling.

## Role check

Sign in with at least an Administrator and a read-only account. Confirm the read-only user does not see administrative or posting workspaces in either the sidebar or Workflow Launcher.

## Acceptance

Accept only if the new grouped navigation is visible, every available destination opens on the first click, no page reports an error, and all existing inventory balances remain unchanged.
