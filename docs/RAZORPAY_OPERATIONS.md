# Razorpay Integration — Configuration, Deployment, Testing, Rollback

Status: implemented in TEST MODE only. Live Mode is rejected by validation (see "Live activation").

## 1. What was added

| Area | Files |
|---|---|
| Gateway client & logic | `integrations/razorpay/{client,orders,verification,payments,webhooks,reconciliation,refunds,guards}.py` |
| API endpoints | `api/razorpay.py` |
| DocTypes | Hotel Payment Gateway Settings (Single), Hotel Payment Transaction, Hotel Payment Refund (child), Hotel Payment Webhook Log |
| Custom fields | Payment Entry: `razorpay_payment_id`, `hotel_payment_transaction` |
| Guest checkout | `www/hotel-pay.html` (+ `.py`) → `/hotel-pay?token=…` |
| Settings dashboard | `doctype/hotel_payment_gateway_settings/hotel_payment_gateway_settings.js` |
| Front Desk Console | `public/js/console/razorpay.js` (new), `dialogs.js` (Receive Payment method selector, online payments list, invoice collect), console CSS |
| Sales Invoice button | `public/js/sales_invoice_razorpay.js` (`doctype_js`) |
| Dashboard | Page `hotel-payment-dashboard` ("Online Payments") |
| Website | `api/website.py` returns `payment` on single-room bookings; patch adds a "Pay advance online" button to Web Page `home` |
| Hooks | Payment Entry `validate` guard, Sales Invoice `doctype_js`, `*/5` cron `payments.expire_and_release` |
| Patches (v3_1) | `razorpay_custom_fields`, `razorpay_navigation` (sidebar items inserted in DB), `website_payment_button` |
| Existing code changed | `api/console.py` (blocks manual Razorpay receipts), `api/website.py`, `setup/custom_fields.py`, `hooks.py`, `patches.txt` |

### Endpoints (`/api/method/hospitality_core.api.razorpay.<name>`)
* Guest, token-bound, rate-limited: `get_payment_context` (GET), `create_order` (POST), `verify_payment` (POST), `report_checkout_event` (POST), `get_payment_status` (GET)
* Webhook: `handle_webhook` (POST, HMAC-verified)
* Staff: `create_reservation_payment_request`, `create_invoice_payment_request`, `get_transaction_status`, `cancel_payment_request`, `get_online_payments`, `get_front_desk_config`
* Gateway admin (System / Accounts Manager): `get_gateway_status`, `test_connection`, `verify_credentials`, `generate_test_payment`, `get_webhook_info`, `disable_gateway`, `setup_accounting_defaults`
* Dashboard: `get_dashboard_data`, `get_transaction_detail`, `retry_reconciliation`, `sync_transaction`, `refund_transaction` & `sync_refunds` (Accounts Manager only)

## 2. Configuration (Sidebar → Payment Gateway)
1. Razorpay Dashboard → switch to **Test Mode** → Account & Settings → API Keys → generate key.
2. In **Hotel Payment Gateway Settings**, enter the Key ID (`rzp_test_…`) and Key Secret. Both are stored as encrypted
   Password fields and are never returned to the browser.
3. Select the Company → **Setup → Create Clearing Account & Mode of Payment**. This creates `Razorpay Clearing - <abbr>`
   (Bank ledger) and the Mode of Payment `Razorpay`. You can also pick existing ones.
4. Set **Public Base URL** to the public https address of the site (used in payment links and the webhook).
5. Pick the scenarios, advance policy (default: 25 %) and website policy (default: Optional = current
   "pay at hotel" behaviour kept), tick **Gateway Enabled**, then Save.
6. **Gateway → Test Connection**: the setup step turns green.

## 3. Webhook setup
1. Razorpay Dashboard (Test Mode) → Webhooks → Add: URL from **Webhook → View Webhook Endpoint**
   (`<public base>/api/method/hospitality_core.api.razorpay.handle_webhook`).
2. Secret: a new random value that is **different from the API Key Secret**. Put the same value in *Webhook Secret*.
3. Events: `payment.captured`, `payment.failed`, `order.paid`.
4. Razorpay can only call a **public HTTPS** URL. This server currently serves plain HTTP on port 80 with the host name
   `frappe.com`, so webhooks will not arrive until the site has a public domain with TLS. You can also test through a tunnel.
   Without webhooks, payments still complete: the browser callback triggers verification on the server, the payment page
   and the console poll Razorpay, and the 5-minute scheduler re-checks pending orders.

## 4. Running the first sandbox payment (initial goal)
1. Complete §2 (and §3 if a public URL is available).
2. Book a single room on the website `/home`. The confirmation shows **Pay advance … online**.
3. On `/hotel-pay`, pay with Razorpay's test card or UPI. The test details are listed in the Razorpay docs under
   "Test card details".
4. Expected result: the page shows "Payment successful", **one** Payment Entry is posted (mode Razorpay,
   paid to Razorpay Clearing, reference `pay_…`, Hotel Reservation set), the reservation shows the payment in the Front Desk
   Console, and the transaction is listed on the Online Payments dashboard as *Reconciled*.

## 5. Accounting model
* Receipt: Payment Entry *Receive* Customer → Dr Razorpay Clearing / Cr Receivable. No income account is touched.
  Reservation advances carry `hotel_reservation`. The existing checkout logic (`allocate_reservation_advances`) therefore
  consumes them automatically. Invoice payments are allocated against the Sales Invoice. Any excess stays an
  unallocated advance.
* Settlement: Razorpay settles to the bank in batches, net of fees. Book it with a Journal Entry (Bank Dr, Razorpay fees Dr,
  Razorpay Clearing Cr) and reconcile it with Bank Reconciliation.
* Refund: a separate *Pay* Payment Entry (Dr Receivable / Cr Clearing). If the refunded payment was already allocated to
  an invoice, follow up with a credit note or a manual reconciliation.
* Idempotency: unique DB keys on order id, payment id, Payment Entry and idempotency key; a row lock during reconciliation;
  an existing Payment Entry with the same `razorpay_payment_id` is reused; webhook event ids are unique.

## 6. Automated test report (2026-11-17, mocked Razorpay API, rolled-back transaction)
`bench --site frappe.com run-tests --module hospitality_core.tests.test_razorpay` → **Ran 19, OK (17 passed, 2 inherited skips)**

| Prompt item | Test |
|---|---|
| 1, 23 config / test-live isolation | test_settings_validation_and_isolation |
| 2, 3 connection ok / invalid creds | test_connection_ok_and_invalid |
| 4, 5 order + server amount | test_order_creation_server_amount |
| 6, 10, 15, 22 signature, capture, advance PE, no duplicate GL | test_reservation_advance_captured_creates_one_payment_entry |
| 7 invalid signature | test_invalid_checkout_signature_rejected |
| 8 failed payment + retry | test_failed_payment_then_retry |
| 9 authorized ≠ paid | test_authorized_not_treated_as_paid |
| 11–14 duplicate/delayed/invalid webhook, duplicate PE | test_webhooks_duplicate_delayed_invalid, test_webhook_endpoint_http_codes |
| 16, 17 invoice + partial | test_sales_invoice_partial_payment |
| 18 reconciliation retry | test_failed_reconciliation_retry |
| 19 front desk | test_front_desk_request_and_manual_block |
| 20 permissions | test_permissions_and_tokens |
| 21 refunds | test_refund_safeguards |
| guest website flow end-to-end | test_guest_checkout_end_to_end |
| unpaid hold release | test_required_advance_hold_released |
| dashboard | test_dashboard_data |

Regression: `test_v3` → Ran 15, OK. `test_website`, `test_flow` and `test_listing` fail **before running** because ERPNext's
test-record bootstrap hits a fiscal-year overlap. This is a pre-existing site data issue and also happens on `main`.
**Real sandbox transaction: not yet performed.** It needs your Razorpay test keys, entered in the UI, and a browser checkout.

## 7. Deployment (as done on this server)
```
bench --site frappe.com backup          # 20261117_172920 backup taken before the first migrate
bench --site frappe.com migrate         # DocTypes, custom fields, v3_1 patches
bench build --app hospitality_core
bench --site frappe.com clear-cache && bench --site frappe.com clear-website-cache
kill -HUP <gunicorn master pid>         # graceful web reload (supervisorctl needs sudo)
sudo supervisorctl restart all          # recommended, so the background workers/scheduler load the new code
```

## 8. Rollback
1. Disable first (safe, instant): Payment Gateway → Gateway → Disable Gateway.
2. Remove the website button:
   `bench --site frappe.com execute hospitality_core.patches.v3_1.website_payment_button.revert`
3. Code: `git checkout main` in `apps/hospitality_core`, then `bench --site frappe.com migrate`, `bench build`, and restart.
   The new DocTypes stay as orphan tables: keep them, because they hold the payment audit trail.
4. Never delete Payment Entries that Razorpay payments created. Cancel or reverse them through standard ERPNext accounting if needed.
5. Full restore, last resort: `bench --site frappe.com restore sites/frappe.com/private/backups/20261117_172920-frappe_com-database.sql.gz`

## 9. Live activation (Phase 15, not implemented)
Live Mode is blocked in `HotelPaymentGatewaySettings.validate` and in `client.get_credentials`. Activation will be a
separate change that adds live credential fields and an Administrator approval record. It must also verify HTTPS, live
webhooks, the settlement account, the capture configuration, the refund policy, and a passing sandbox suite with
end-to-end reconciliation.

## 10. Known limitations
* Online advances are offered only for single-room website bookings. Front desk can send one link per reservation.
* Webhook delivery needs a public HTTPS URL (see §3).
* The home page formats amounts without decimals (existing `money()` helper). The checkout page shows the exact amount.
* `get_billing_summary` / the console bill show charges *up to today*. The payment ceiling uses the full stay up to check-out.
