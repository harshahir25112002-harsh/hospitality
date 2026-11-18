# Hospitality Core v3: Front Desk Console overhaul

Checkpoint before this work: git tag `pre-v3-overhaul` and the database backup
`sites/frappe.com/private/backups/20261116_122140-frappe_com-database.sql.gz`.

## What changed

### Front Desk Console (`/desk/hospitality-core/front-desk-console`)
- **Root cause of "page does not open":** `on_page_load` called `wrapper.find()` on a plain DOM
  element. The exception stopped Frappe from switching to the page, so the workspace stayed on
  screen. The wrapper is now a jQuery object, and startup and load errors show an error panel with a Retry button.
- **Layout:** a sticky header (brand, date navigation, global search, actions), 9 KPI cards you can click,
  and 9 in-page tabs: Room Board, Arrivals, In-House, Departures, Reservations, Tape Chart,
  Housekeeping, Maintenance and Availability.
- **No navigation away:** every action is a dialog. A Link field's "Create new …" always opens a
  Quick Entry popup. The link-open arrow shows a read-only preview popup. Print opens in a popup.
- **POS:** the standard ERPNext Point of Sale opens in a full-screen overlay (iframe), with an
  "Open in new tab" fallback. Room Service first asks you to pick the in-house guest.
- **Code layout:** `public/js/console/{core,views,dialogs,pos_overlay}.js`, combined into the
  page script on the server with Frappe's page include directive. The Page registration is unchanged.
- **Styling:** uses Frappe CSS variables (light and dark themes), Lucide icons via
  `frappe.utils.icon`, and responsive layouts for tablets and phones (tables stack on phones).

### Reservation logic
- **Availability is date-based.** A future booking no longer marks the room "Reserved" today, so the
  room can still be sold for other dates. The room status of Dirty, Out of Order or Occupied blocks a
  booking only when the stay starts today. Check-in still requires a clean (Available or Reserved) room.
- **A daily scheduler (`mark_todays_arrivals`)** flags rooms Reserved on the arrival day.
- Rows are locked (`SELECT … FOR UPDATE`) on booking, check-in, move and check-out.
- Extending a stay checks for conflicts. Change Room for not-yet-arrived bookings
  (`change_reserved_room`) is new.

### Accounting (standard ERPNext documents only)
- **Advances:** the checkout Sales Invoice now consumes only Payment Entries linked to the
  **same reservation**. Before, ERPNext's automatic allocation could use a guest's deposit for a
  different, future booking.
- A second checkout invoice for the same reservation is blocked.
- `receive_payment` rejects amounts of zero or less, and payments on cancelled or checked-out reservations.
- No GL entries are written directly. Payment Entry and Sales Invoice go through standard validation and submit.

### POS (`public/js/pos_extension.js`, loaded through `page_js`)
- The standard POS opens the user's most recent POS Opening Entry. The extension only re-orders the
  opening entries so the profile you clicked (Restaurant or Room Service) is used.
- The In-House Guest picker sets both the customer and `hotel_reservation`.
- "Charge to Room" saves the cart through the standard POS form and then calls `pos.charge_to_room`.
  The server checks that the order's customer matches the reservation's guest.

### Console API (`hospitality_core/api/console.py`)
- Every endpoint requires one of: Hospitality User, System Manager, Accounts User or Accounts Manager.
- New endpoints: `get_reservation_details`, `get_reservations`, `change_reserved_room`,
  `create_sample_rooms` (System Manager only), plus setup warnings in `get_console_data`.
- `create_reservation` accepts only known fields from the client.

## Tests
`bench --site <site> run-tests --app hospitality_core` runs:
- `tests/test_flow.py`: the original lifecycle and POS scenarios A–G (2 tests).
- `tests/test_v3.py` (13 tests):
  - advance isolation
  - duplicate checkout
  - extend-stay conflict
  - double booking and moving into an occupied room
  - payment validation and multiple payments
  - room-service revenue recognised exactly once (GL income check)
  - charge-to-room for the wrong guest
  - tax on the checkout invoice
  - console API
  - walk-in and booking with an advance
  - housekeeping rules
  - maintenance issue
  - permissions

Tests run inside a transaction that is rolled back. The live bench shares Redis, so `test_v3` reads
Hotel Settings from the database rather than the cache.

## Deploy / upgrade
```bash
cd ~/frappe-bench
bench --site <site> backup
git -C apps/hospitality_core pull            # or check out the release
bench --site <site> migrate                  # no schema changes in v3, safe to run
bench build --app hospitality_core
bench --site <site> clear-cache
bench restart                                # or: kill -HUP <gunicorn master pid>
```
Then set up **Hotel Settings**. The console shows warnings and has a Settings popup. Set: Company, Default Room Item,
Restaurant POS Profile, Room Service POS Profile, Default Mode of Payment and, optionally, Sales Taxes Template.

## Rollback
```bash
git -C apps/hospitality_core checkout pre-v3-overhaul
bench build --app hospitality_core && bench --site <site> clear-cache && bench restart
# data rollback only if required:
bench --site <site> restore sites/<site>/private/backups/<backup>-database.sql.gz
```
v3 has no schema changes, so rolling back the code needs no data migration.

## Open business questions (not decided in code)
1. **Refund on cancellation:** advances stay as unallocated Payment Entries. A refund is a
   manual Payment Entry (Pay). Should cancellation fees be charged?
2. **Early check-in billing:** check-in moves the first night's start to today (existing behaviour).
   Is an early arrival billed from the actual check-in date (current behaviour) or from the booked date?
3. **Same-day booking of a Dirty room** is allowed; check-in stays blocked until it is clean. Is that the policy you want?
4. **Late checkout / day use:** only "minimum billable nights" exists. Is a late-checkout charge needed?

## Not verified in this environment
- No logged-in browser was available. The UI was checked by running the real served page script in
  jsdom with stubbed Frappe APIs (every tab and dialog renders and the actions call the right endpoints).
  It still needs a manual check in Chrome, including dark mode.
- The POS overlay with profile selection and guest preselection inside the real POS iframe.
- POS Closing Entry is standard ERPNext and was not changed or tested.
- Row locks were added but not load-tested with truly simultaneous requests.
- The standalone Tape Chart, Housekeeping View and Availability Tool pages are unchanged. Their
  improved versions are the console tabs.
