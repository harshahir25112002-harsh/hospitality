# Razorpay Integration — Phase 0 Audit & Architecture

## 1. Audited environment (2026-11-17)

| Item | Finding |
|---|---|
| Frappe | 17.x.x-develop (5fe4b64) |
| ERPNext | 17.x.x-develop (50c9e78) |
| Hospitality Core | 0.0.1 / "v3.0 console", branch `main` @ 436406e, clean tree |
| Python | 3.14.10 |
| Site | `frappe.com` (only site), Company `Demo` (INR), tz Asia/Kolkata |
| Serving | supervisor + gunicorn :8000, nginx :80, **no HTTPS** |
| Outbound | `api.razorpay.com` and `checkout.razorpay.com` reachable |
| Razorpay SDK | not installed. **Decision:** use `requests` (already installed) — avoids an extra dependency and the SDK's `pkg_resources` import issues on Python 3.14 |
| Existing gateway code | none (no Razorpay, no `payments` app, no Payment Gateway doctype). ERPNext `Payment Request` exists but is tied to the `payments` app gateways — not used |

### Existing payment logic (reused, not duplicated)
* `api/console.py::receive_payment` / `create_reservation(advance=…)` — Receive Payment Entry with
  `hotel_reservation` custom field, `paid_from` = company receivable, `paid_to` = Mode of Payment account.
* `hotel_reservation.py::allocate_reservation_advances` — at checkout only Payment Entries whose
  `hotel_reservation` is this reservation are allocated. **A Razorpay advance PE with the same link is
  therefore consumed automatically at checkout — no change needed.**
* `get_billing_summary` — estimated_total / total_paid / balance, already sums PEs by reservation.
* `api/website.py::create_booking` — public booking, server-side pricing, idempotent `booking_token`,
  row locking. Bookings are created directly as `Reserved` ("payment is settled at the hotel").
* Website UI is a DB-stored **Web Page `home`** (HTML + 64 KB JS), *not* in git.
* Front Desk Console v3: `public/js/console/dialogs.js::dialog_receive_payment` (Mode-of-Payment link).
* Accounts: only `Cash - D` exists as Bank/Cash ledger; no clearing account; no Razorpay MoP.

### Test baseline
`bench run-tests --module hospitality_core.tests.test_v3` → 15 tests OK (2 skipped).
`test_website`, `test_flow`, `test_listing`, full `--app` run fail **before any app test runs** in ERPNext's
global test-record bootstrap ("Fiscal Year 2026-2027 overlapping") — pre-existing site data issue.

## 2. Architecture

```
Guest browser ─► /hotel-pay?token=…  (www page, Razorpay checkout.js)
                    │ create_order(token)      verify_payment(token, ids, signature)
                    ▼                                │
         api/razorpay.py (whitelisted, rate-limited) ◄┘
                    │
   integrations/razorpay/  client.py ── HTTPS Basic auth ──► api.razorpay.com/v1
                           orders.py  (request → order, amount always server-side)
                           verification.py (checkout + webhook HMAC, payment fetch/capture)
                           webhooks.py  (event-id idempotency → Hotel Payment Webhook Log)
                           reconciliation.py (Captured → exactly one ERPNext Payment Entry)
                           refunds.py  (role-gated, Razorpay refund API, Pay PE)
Razorpay ── webhook ──► /api/method/hospitality_core.api.razorpay.handle_webhook
Front Desk Console ─► create_payment_request ─► link + QR / open checkout on this screen ─► polls status
```

### DocTypes (new)
* **Hotel Payment Gateway Settings** (Single, System Manager / Accounts Manager): enabled, environment
  (Test only — Live is rejected in `validate`), test Key ID / Key Secret / Webhook Secret (Password fields,
  encrypted in `__Auth`), company, currency, receivable override, **Razorpay clearing account**, Mode of
  Payment, description, allowed scenarios, advance policy, pending-hold policy, link expiry, auto-capture,
  partial-invoice policy, public base URL, and read-only health state (last connection test, last
  webhook, etc.). The form renders a gateway dashboard + setup progress from live backend state.
* **Hotel Payment Transaction**: one row per payment request. Unique `razorpay_order_id`,
  `razorpay_payment_id`, `payment_entry`, `idempotency_key`; hashed guest access token; status lifecycle.
* **Hotel Payment Webhook Log**: unique Razorpay event id → duplicate webhook protection + audit.
* **Hotel Payment Refund** (child of transaction): refund id, amount, status, Pay Payment Entry.

### Custom fields
`Payment Entry.razorpay_payment_id` (read-only, no_copy, indexed) and
`Payment Entry.hotel_payment_transaction` (Link).

### Key rules
* Amount is computed on the server when the request is created and re-checked against the current
  balance/outstanding when the order is created. The browser never supplies a guest amount; staff may
  request *less* than the balance, never more.
* Checkout success handler → only triggers server verification (HMAC + API fetch of the payment).
  `authorized` is never treated as paid; it is captured server-side (if enabled) and re-fetched.
* Network calls happen **before** taking row locks (`SELECT … FOR UPDATE` on the transaction).
* Reconciliation is idempotent: row lock + `payment_entry` already set → no-op; DB unique keys on
  order/payment ids; existing PE with the same `razorpay_payment_id` is reused.
* Payment Entry: Receive / Customer / receivable → clearing account / Razorpay MoP /
  reference_no = `pay_…`; reservation advances carry `hotel_reservation`; invoice payments are allocated
  against the Sales Invoice. Standard `insert()` + `submit()` only — no GL or SQL writes.
* Captured ≠ settled: money sits in the clearing account until settlement is booked by Accounts.
* Multi-room website bookings: online advance is offered only for single-reservation bookings (a single
  Razorpay payment must map to exactly one Payment Entry and one reservation). Front desk can send a
  link per reservation.
* Pending hold: policy `Optional` (default, current behaviour preserved) or `Required` (unpaid website
  reservations auto-cancel after N minutes via scheduler, using the existing cancel flow).
* Live mode is blocked in this release (Phase 15 is a separate, explicit activation process).
