"""Razorpay integration tests (mocked Razorpay API, rolled-back transaction).

Run: bench --site <site> run-tests --module hospitality_core.tests.test_razorpay
"""
import hashlib
import hmac
import json
import secrets
from types import SimpleNamespace
from unittest import mock

import frappe
from frappe.utils import add_days, add_to_date, flt, getdate, now_datetime, nowdate

from hospitality_core.api import console
from hospitality_core.api import razorpay as api
from hospitality_core.integrations.razorpay import client, orders, payments, reconciliation, refunds, webhooks
from hospitality_core.tests import test_flow

KEY_ID = "rzp_test_HcUnitTest1234"
KEY_SECRET = "unit_test_key_secret_value"
WEBHOOK_SECRET = "unit_test_webhook_secret"
TXN = "Hotel Payment Transaction"


class FakeRazorpay:
    """In-memory stand-in for api.razorpay.com/v1 (only what the integration uses)."""

    def __init__(self):
        self.orders, self.payments, self.refunds, self.calls = {}, {}, {}, []
        self.fail_auth = False

    @staticmethod
    def _id(prefix):
        return prefix + secrets.token_hex(7)

    def request(self, method, path, payload=None, params=None, creds=None):
        self.calls.append((method, path))
        if self.fail_auth:
            raise client.RazorpayError("Razorpay rejected the API credentials (authentication failed).", 401)
        parts = path.strip("/").split("/")
        if method == "GET" and parts == ["orders"]:
            return {"items": [], "count": 0}
        if method == "POST" and parts == ["orders"]:
            o = {"id": self._id("order_"), "amount": payload["amount"], "currency": payload["currency"],
                 "receipt": payload["receipt"], "notes": payload["notes"], "status": "created"}
            self.orders[o["id"]] = o
            return o
        if parts[0] == "orders" and len(parts) == 3:
            return {"items": [p for p in self.payments.values() if p["order_id"] == parts[1]]}
        if parts[0] == "payments" and len(parts) == 2:
            return dict(self.payments[parts[1]])
        if parts[0] == "payments" and parts[2] == "capture":
            p = self.payments[parts[1]]
            assert payload["amount"] == p["amount"]
            p.update(status="captured", captured=True)
            return dict(p)
        if parts[0] == "payments" and parts[2] == "refund":
            r = {"id": self._id("rfnd_"), "amount": payload["amount"], "payment_id": parts[1], "status": "processed"}
            self.refunds[r["id"]] = r
            return r
        if parts[0] == "payments" and parts[2] == "refunds":
            return self.refunds[parts[3]]
        raise AssertionError(f"unexpected call {method} {path}")

    def pay(self, order_id, status="captured", amount=None):
        o = self.orders[order_id]
        p = {"id": self._id("pay_"), "entity": "payment", "order_id": order_id, "amount": amount or o["amount"],
             "currency": o["currency"], "status": status, "captured": status == "captured", "method": "card",
             "error_description": "Card declined by bank" if status == "failed" else None,
             "acquirer_data": {"rrn": "123456789012"}, "created_at": 1700000000 + len(self.payments)}
        self.payments[p["id"]] = p
        return p


def checkout_signature(order_id, payment_id, secret=KEY_SECRET):
    return hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


def webhook_body(event, payment):
    body = json.dumps({"entity": "event", "event": event, "payload": {"payment": {"entity": payment}}}).encode()
    sig = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, sig


class TestRazorpay(test_flow.TestHotelFlow):
    def test_complete_hotel_lifecycle(self):
        self.skipTest("covered by TestHotelFlow")

    def test_pos_scenarios_a_to_g(self):
        self.skipTest("covered by TestHotelFlow")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        out = api.setup_accounting_defaults(cls.company)
        cls.clearing, cls.mop = out["clearing_account"], out["mode_of_payment"]

    def setUp(self):
        frappe.set_user("Administrator")
        fresh = lambda: frappe.get_doc("Hotel Settings")
        for target in ("hospitality_core.utils.get_settings", "hospitality_core.api.console.get_settings",
                       "hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation.get_settings"):
            p = mock.patch(target, side_effect=fresh)
            p.start()
            self.addCleanup(p.stop)
        for name in frappe.get_all("Hotel Reservation", filters={"status": ["in", ["Reserved", "Checked In"]]}, pluck="name"):
            frappe.db.set_value("Hotel Reservation", name, "status", "Cancelled")
        for r in self.rooms:
            frappe.db.set_value("Hotel Room", r, {"status": "Available", "current_reservation": None})
        frappe.db.set_single_value("Hotel Settings", "sales_taxes_template", None)

        self.fake = FakeRazorpay()
        p = mock.patch.object(client, "request", side_effect=self.fake.request)
        p.start()
        self.addCleanup(p.stop)

        s = frappe.get_doc(client.SETTINGS)
        s.update({"enabled": 1, "environment": "Test", "test_key_id": KEY_ID, "test_key_secret": KEY_SECRET,
                  "test_webhook_secret": WEBHOOK_SECRET, "company": self.company, "default_currency": self.currency,
                  "clearing_account": self.clearing, "mode_of_payment": self.mop, "receivable_account": None,
                  "allow_website_advance": 1, "allow_front_desk": 1, "allow_invoice_payment": 1,
                  "allow_partial_invoice_payment": 1, "auto_capture": 1, "advance_type": "Percentage",
                  "advance_value": 25, "website_payment_policy": "Optional", "pending_hold_minutes": 30,
                  "link_expiry_minutes": 1440, "public_base_url": "https://hotel.example.test"})
        s.save()
        self.today = getdate(nowdate())

    # ------------------------------------------------------------------ helpers
    def make_res(self, room, start, end, checkin=False):
        from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import check_in
        res = frappe.get_doc({
            "doctype": "Hotel Reservation", "company": self.company, "customer": self.customer_name,
            "room_type": self.room_type, "room": room, "check_in_date": start, "check_out_date": end, "adults": 1,
        }).insert(ignore_permissions=True)
        if checkin:
            check_in(res.name)
            res.reload()
        return res

    def request_for(self, res, amount=None):
        txn, token = orders.front_desk_request(res.name, amount)
        return txn, token

    def checkout(self, token, status="captured"):
        txn = orders.ensure_order(orders.get_txn_by_token(token, for_payment=True))
        pay = self.fake.pay(txn.razorpay_order_id, status=status)
        payments.verify_checkout(txn, txn.razorpay_order_id, pay["id"], checkout_signature(txn.razorpay_order_id, pay["id"]))
        return frappe.get_doc(TXN, txn.name), pay

    def pes_for(self, payment_id):
        return frappe.get_all("Payment Entry", filters={"razorpay_payment_id": payment_id, "docstatus": 1}, pluck="name")

    # ------------------------------------------------------------------ 1, 23 configuration & isolation
    def test_settings_validation_and_isolation(self):
        s = frappe.get_doc(client.SETTINGS)
        s.environment = "Live"
        self.assertRaises(frappe.ValidationError, s.save)
        s.reload()
        s.test_key_id = "rzp_live_ABCDEFGHIJKL"
        self.assertRaises(frappe.ValidationError, s.save)
        s.reload()
        s.clearing_account = None
        self.assertRaises(frappe.ValidationError, s.save)  # cannot stay enabled without accounting
        s.reload()
        creds = client.get_credentials()
        self.assertEqual(creds.key_id, KEY_ID)
        self.assertNotIn(KEY_SECRET, repr(creds))
        frappe.db.set_single_value(client.SETTINGS, "environment", "Live")  # even if forced in the DB
        self.assertRaises(client.GatewayDisabled, client.get_credentials)
        frappe.db.set_single_value(client.SETTINGS, "environment", "Test")
        status = api.get_gateway_status()
        self.assertNotIn(KEY_SECRET, json.dumps(status, default=str))
        self.assertEqual(status["environment"], "Test")

    # ------------------------------------------------------------------ 2, 3 connection
    def test_connection_ok_and_invalid(self):
        r = api.test_connection()
        self.assertTrue(r["ok"])
        self.assertTrue(next(x for x in api.get_gateway_status()["steps"] if x["key"] == "connection")["done"])
        self.fake.fail_auth = True
        r = api.test_connection()
        self.assertFalse(r["ok"])
        self.assertIn("authentication", r["message"])
        self.assertNotIn(KEY_SECRET, r["message"])

    # ------------------------------------------------------------------ 4, 5 orders & server-side amount
    def test_order_creation_server_amount(self):
        res = self.make_res(self.rooms[0], add_days(self.today, 3), add_days(self.today, 5))  # 2 future nights
        rate = flt(res.stays[0].rate)
        total = orders.reservation_balance(res.name)[1]["estimated_total"]
        self.assertEqual(total, flt(2 * rate, 2))  # full stay, not "billed up to today"
        info = orders.website_advance_request(res.name)
        self.assertEqual(flt(info["amount"]), flt(total * 0.25, 2))  # computed on the server
        self.assertTrue(info["url"].startswith("https://hotel.example.test/hotel-pay?token="))
        token = info["url"].split("token=")[1]
        txn = orders.ensure_order(orders.get_txn_by_token(token, for_payment=True))
        order = self.fake.orders[txn.razorpay_order_id]
        self.assertEqual(order["amount"], int(round(total * 0.25 * 100)))
        self.assertEqual(order["notes"]["hotel_payment_transaction"], txn.name)
        # second call reuses the order
        again = orders.ensure_order(frappe.get_doc(TXN, txn.name))
        self.assertEqual(again.razorpay_order_id, txn.razorpay_order_id)
        self.assertEqual(len(self.fake.orders), 1)
        # staff can never request more than the balance
        self.assertRaises(frappe.ValidationError, orders.front_desk_request, res.name, total + 1)
        ctx = orders.public_context(again, include_checkout=True)
        self.assertEqual(ctx["checkout"]["key"], KEY_ID)
        self.assertNotIn(KEY_SECRET, json.dumps(ctx, default=str))

    # ------------------------------------------------------------------ 6, 10, 15, 22 success path
    def test_reservation_advance_captured_creates_one_payment_entry(self):
        res = self.make_res(self.rooms[0], add_days(self.today, 3), add_days(self.today, 4))
        info = orders.website_advance_request(res.name)
        token = info["url"].split("token=")[1]
        txn, pay = self.checkout(token)
        self.assertEqual(txn.status, "Reconciled")
        pes = self.pes_for(pay["id"])
        self.assertEqual(len(pes), 1)
        pe = frappe.get_doc("Payment Entry", pes[0])
        self.assertEqual((pe.payment_type, pe.party, pe.paid_to, pe.mode_of_payment, pe.hotel_reservation),
                         ("Receive", res.customer, self.clearing, self.mop, res.name))
        self.assertEqual(flt(pe.paid_amount), flt(flt(res.stays[0].rate) * 0.25, 2))
        self.assertEqual(pe.reference_no, pay["id"])
        gl = frappe.get_all("GL Entry", filters={"voucher_no": pe.name, "is_cancelled": 0}, fields=["account", "debit", "credit"])
        self.assertEqual(len(gl), 2)  # clearing Dr / receivable Cr - no income account touched
        self.assertFalse([g for g in gl if g.account not in (self.clearing, pe.paid_from)])
        details = console.get_reservation_details(res.name)
        self.assertEqual(flt(details["billing"]["total_paid"]), flt(pe.paid_amount))
        self.assertEqual(orders.public_context(txn)["status"], "paid")

    # ------------------------------------------------------------------ 7 invalid signature
    def test_invalid_checkout_signature_rejected(self):
        res = self.make_res(self.rooms[0], add_days(self.today, 3), add_days(self.today, 4))
        txn, token = self.request_for(res)
        txn = orders.ensure_order(txn)
        pay = self.fake.pay(txn.razorpay_order_id)
        self.assertRaises(frappe.ValidationError, payments.verify_checkout, txn, txn.razorpay_order_id, pay["id"], "0" * 64)
        self.assertRaises(frappe.ValidationError, payments.verify_checkout, txn, "order_someoneelse1", pay["id"],
                          checkout_signature("order_someoneelse1", pay["id"]))
        self.assertEqual(frappe.db.get_value(TXN, txn.name, "status"), "Order Created")
        self.assertFalse(self.pes_for(pay["id"]))

    # ------------------------------------------------------------------ 8 failed, then retry succeeds
    def test_failed_payment_then_retry(self):
        res = self.make_res(self.rooms[0], add_days(self.today, 3), add_days(self.today, 4))
        txn, token = self.request_for(res)
        txn, _ = self.checkout(token, status="failed")
        self.assertEqual(txn.status, "Failed")
        self.assertIn("declined", txn.failure_reason)
        txn, pay = self.checkout(token, status="captured")  # same order, second attempt
        self.assertEqual(txn.status, "Reconciled")
        self.assertEqual(len(self.pes_for(pay["id"])), 1)

    # ------------------------------------------------------------------ 9 authorized without capture
    def test_authorized_not_treated_as_paid(self):
        frappe.db.set_single_value(client.SETTINGS, "auto_capture", 0)
        res = self.make_res(self.rooms[0], add_days(self.today, 3), add_days(self.today, 4))
        txn, token = self.request_for(res)
        txn, pay = self.checkout(token, status="authorized")
        self.assertEqual(txn.status, "Authorized")
        self.assertFalse(txn.payment_entry)
        self.assertFalse(self.pes_for(pay["id"]))
        self.assertEqual(orders.public_context(txn)["status"], "processing")
        # with auto capture, the server captures for the exact order amount
        frappe.db.set_single_value(client.SETTINGS, "auto_capture", 1)
        self.assertEqual(payments.sync_transaction(txn.name), "Reconciled")
        self.assertEqual(self.fake.payments[pay["id"]]["status"], "captured")

    # ------------------------------------------------------------------ 11, 12, 13, 14 webhooks & idempotency
    def test_webhooks_duplicate_delayed_invalid(self):
        res = self.make_res(self.rooms[0], add_days(self.today, 3), add_days(self.today, 4))
        txn, token = self.request_for(res)
        txn = orders.ensure_order(txn)
        pay = self.fake.pay(txn.razorpay_order_id)
        body, sig = webhook_body("payment.captured", pay)
        # invalid signature
        with self.assertRaises(webhooks.WebhookRejected):
            webhooks.process(body, "f" * 64, "evt_bad")
        with self.assertRaises(webhooks.WebhookRejected):  # signed with the API secret instead of webhook secret
            webhooks.process(body, hmac.new(KEY_SECRET.encode(), body, hashlib.sha256).hexdigest(), "evt_bad2")
        self.assertEqual(frappe.db.get_value(TXN, txn.name, "status"), "Order Created")
        # webhook without any browser callback
        self.assertEqual(webhooks.process(body, sig, "evt_1")["status"], "processed")
        self.assertEqual(frappe.db.get_value(TXN, txn.name, "status"), "Reconciled")
        # duplicate delivery of the same event
        self.assertEqual(webhooks.process(body, sig, "evt_1")["status"], "duplicate")
        # delayed / repeated: different event id, browser callback after the webhook
        self.assertEqual(webhooks.process(body, sig, "evt_2")["status"], "processed")
        payments.verify_checkout(frappe.get_doc(TXN, txn.name), txn.razorpay_order_id, pay["id"],
                                 checkout_signature(txn.razorpay_order_id, pay["id"]))
        # out-of-order failure event never undoes the success
        failed = dict(pay, status="failed")
        fbody, fsig = webhook_body("payment.failed", failed)
        webhooks.process(fbody, fsig, "evt_3")
        self.assertEqual(frappe.db.get_value(TXN, txn.name, "status"), "Reconciled")
        self.assertEqual(len(self.pes_for(pay["id"])), 1)
        self.assertEqual(len(frappe.get_all("Payment Entry", filters={"hotel_payment_transaction": txn.name, "docstatus": 1})), 1)

    def test_webhook_endpoint_http_codes(self):
        body, sig = webhook_body("payment.captured", {"id": "pay_x", "order_id": "order_unknown1"})
        req = SimpleNamespace(get_data=lambda cache=True: body, headers={"X-Razorpay-Signature": "bad", "X-Razorpay-Event-Id": "evt_h1"})
        with mock.patch.object(frappe.local, "request", req, create=True), \
                mock.patch.object(frappe.local, "request_ip", "127.0.0.1", create=True):
            frappe.local.response = frappe._dict()
            out = api.handle_webhook()
            self.assertEqual(frappe.local.response.get("http_status_code"), 400)
            self.assertEqual(out["status"], "rejected")
            req.headers["X-Razorpay-Signature"] = sig
            frappe.local.response = frappe._dict()
            self.assertEqual(api.handle_webhook()["status"], "ignored")  # not our order

    # ------------------------------------------------------------------ 16, 17 Sales Invoice (partial)
    def make_invoice(self, amount=300):
        inv = frappe.new_doc("Sales Invoice")
        inv.company, inv.customer = self.company, self.customer_name
        inv.append("items", {"item_code": self.item_code, "qty": 1, "rate": amount})
        inv.insert()
        inv.submit()
        return inv

    def test_sales_invoice_partial_payment(self):
        inv = self.make_invoice(300)
        self.assertRaises(frappe.ValidationError, orders.invoice_request, inv.name, 301)  # no overpayment
        txn, token = orders.invoice_request(inv.name, 120)
        txn, pay = self.checkout(token)
        self.assertEqual(txn.status, "Reconciled")
        pe = frappe.get_doc("Payment Entry", txn.payment_entry)
        self.assertEqual(pe.references[0].reference_name, inv.name)
        self.assertEqual(flt(pe.references[0].allocated_amount), 120)
        self.assertEqual(flt(frappe.db.get_value("Sales Invoice", inv.name, "outstanding_amount")), 180)
        frappe.db.set_single_value(client.SETTINGS, "allow_partial_invoice_payment", 0)
        self.assertRaises(frappe.ValidationError, orders.invoice_request, inv.name, 50)
        txn2, token2 = orders.invoice_request(inv.name)
        self.assertEqual(flt(txn2.amount), 180)
        txn2, _ = self.checkout(token2)
        self.assertEqual(flt(frappe.db.get_value("Sales Invoice", inv.name, "outstanding_amount")), 0)
        self.assertRaises(frappe.ValidationError, orders.invoice_request, inv.name)  # nothing left to pay

    # ------------------------------------------------------------------ 18 failed reconciliation retry
    def test_failed_reconciliation_retry(self):
        res = self.make_res(self.rooms[0], add_days(self.today, 3), add_days(self.today, 4))
        txn, token = self.request_for(res)
        with mock.patch.object(reconciliation, "accounting_config", side_effect=frappe.ValidationError("ledger closed")):
            txn, pay = self.checkout(token)
        self.assertEqual(txn.status, "Reconciliation Pending")
        self.assertFalse(self.pes_for(pay["id"]))
        out = api.retry_reconciliation(txn.name)
        self.assertEqual(out["status"], "Reconciled")
        self.assertEqual(len(self.pes_for(pay["id"])), 1)
        api.sync_transaction(txn.name)  # repeated sync is a no-op
        self.assertRaises(frappe.ValidationError, api.retry_reconciliation, txn.name)
        self.assertEqual(len(self.pes_for(pay["id"])), 1)

    # ------------------------------------------------------------------ 19 front desk
    def test_front_desk_request_and_manual_block(self):
        res = self.make_res(self.rooms[0], self.today, add_days(self.today, 2), checkin=True)
        out = api.create_reservation_payment_request(res.name, 150, "fd-key-1")
        self.assertTrue(out["pay_url"].startswith("https://hotel.example.test/hotel-pay?token="))
        self.assertTrue(out["qr_svg"] and out["qr_svg"].lstrip().startswith("<svg"))
        again = api.create_reservation_payment_request(res.name, 150, "fd-key-1")  # double click
        self.assertEqual(again["transaction"]["name"], out["transaction"]["name"])
        newer = api.create_reservation_payment_request(res.name, 100, "fd-key-2")  # supersedes the old one
        self.assertEqual(frappe.db.get_value(TXN, out["transaction"]["name"], "status"), "Cancelled")
        token = newer["pay_url"].split("token=")[1]
        txn, pay = self.checkout(token)
        self.assertEqual(api.get_transaction_status(txn.name)["status"], "Reconciled")
        self.assertTrue(any(p.name == txn.payment_entry for p in console.get_reservation_details(res.name)["payments"]))
        self.assertRaises(frappe.ValidationError, console.receive_payment, res.name, self.mop, 10)
        # the superseded request's link (rotated on the double click) can no longer be paid
        self.assertRaises(frappe.ValidationError, orders.get_txn_by_token, again["pay_url"].split("token=")[1], True)
        self.assertRaises(frappe.PermissionError, orders.get_txn_by_token, out["pay_url"].split("token=")[1], True)

    # ------------------------------------------------------------------ 20 permissions & token access
    def test_permissions_and_tokens(self):
        res = self.make_res(self.rooms[0], add_days(self.today, 3), add_days(self.today, 4))
        txn, token = self.request_for(res)
        frappe.set_user("Guest")
        try:
            self.assertRaises(frappe.PermissionError, api.create_reservation_payment_request, res.name)
            self.assertRaises(frappe.PermissionError, api.get_dashboard_data)
            self.assertRaises(frappe.PermissionError, api.test_connection)
            self.assertRaises(frappe.PermissionError, api.retry_reconciliation, txn.name)
            self.assertRaises(frappe.PermissionError, api.refund_transaction, txn.name, 1, "x")
            self.assertRaises(frappe.PermissionError, api.get_payment_context, "x" * 43)
            self.assertRaises(frappe.PermissionError, api.get_payment_context, "short")
            ctx = api.get_payment_context(token)
            self.assertEqual(ctx["reservation"], res.name)
            self.assertNotIn("razorpay_order_id", ctx)
            self.assertFalse(frappe.has_permission(TXN, "read"))
        finally:
            frappe.set_user("Administrator")
        frappe.db.set_value(TXN, txn.name, "expires_on", add_to_date(now_datetime(), minutes=-1))
        self.assertRaises(frappe.ValidationError, orders.get_txn_by_token, token, True)

    # ------------------------------------------------------------------ guest end-to-end (website)
    def test_guest_checkout_end_to_end(self):
        res = self.make_res(self.rooms[0], add_days(self.today, 3), add_days(self.today, 5))
        frappe.set_user("Guest")
        try:
            from hospitality_core.api.website import _online_payment_offer
            offer = _online_payment_offer({"booking_references": [res.name], "status": "Reserved"})
            self.assertTrue(offer and offer["amount"] > 0)
            self.assertEqual(frappe.session.user, "Guest")  # system-user switch fully restored
            self.assertEqual(frappe.session.sid, "Guest")
            token = offer["url"].split("token=")[1]
            ctx = api.create_order(token)
            self.assertTrue(ctx["checkout"]["order_id"].startswith("order_"))
            self.assertEqual(ctx["checkout"]["amount"], int(round(offer["amount"] * 100)))
            pay = self.fake.pay(ctx["checkout"]["order_id"])
            out = api.verify_payment(token, ctx["checkout"]["order_id"], pay["id"],
                                     checkout_signature(ctx["checkout"]["order_id"], pay["id"]))
            self.assertEqual(out["status"], "paid")
            self.assertEqual(frappe.session.user, "Guest")
            self.assertNotIn(KEY_SECRET, json.dumps(out, default=str))
        finally:
            frappe.set_user("Administrator")
        pes = self.pes_for(pay["id"])
        self.assertEqual(len(pes), 1)
        self.assertEqual(frappe.db.get_value("Payment Entry", pes[0], "owner"), "Administrator")
        # multi-room bookings are not offered an online advance (one payment -> one reservation)
        from hospitality_core.api.website import _online_payment_offer
        self.assertIsNone(_online_payment_offer({"booking_references": [res.name, "X"], "status": "Reserved"}))

    # ------------------------------------------------------------------ 21 refunds
    def test_refund_safeguards(self):
        res = self.make_res(self.rooms[0], add_days(self.today, 3), add_days(self.today, 4))
        txn, token = self.request_for(res, 100)
        txn, pay = self.checkout(token)
        user = "rzp-frontdesk@example.test"
        if not frappe.db.exists("User", user):
            frappe.get_doc({"doctype": "User", "email": user, "first_name": "Front Desk", "send_welcome_email": 0,
                            "roles": [{"role": "Hospitality User"}]}).insert(ignore_permissions=True)
        frappe.set_user(user)
        try:
            self.assertRaises(frappe.PermissionError, refunds.initiate_refund, txn.name, 10, "x")
            self.assertRaises(frappe.PermissionError, api.refund_transaction, txn.name, 10, "x")
            self.assertRaises(frappe.PermissionError, api.test_connection)
            api.get_transaction_status(txn.name)  # front desk can see status
        finally:
            frappe.set_user("Administrator")
        self.assertRaises(frappe.ValidationError, refunds.initiate_refund, txn.name, 101, "too much")
        self.assertRaises(frappe.ValidationError, refunds.initiate_refund, txn.name, 10, "")
        refunds.initiate_refund(txn.name, 40, "Guest request")
        txn.reload()
        self.assertEqual(txn.status, "Partially Refunded")
        self.assertEqual(flt(txn.refunded_amount), 40)
        rpe = frappe.get_doc("Payment Entry", txn.refunds[0].payment_entry)
        self.assertEqual((rpe.payment_type, rpe.paid_from, flt(rpe.paid_amount)), ("Pay", self.clearing, 40))
        self.assertRaises(frappe.ValidationError, refunds.initiate_refund, txn.name, 61, "over")
        refunds.initiate_refund(txn.name, 60, "rest")
        self.assertEqual(frappe.db.get_value(TXN, txn.name, "status"), "Refunded")
        # cancelling a reservation never refunds automatically
        res2 = self.make_res(self.rooms[1], add_days(self.today, 3), add_days(self.today, 4))
        t2, tok2 = self.request_for(res2, 50)
        self.checkout(tok2)
        n_refund_calls = len([c for c in self.fake.calls if c[1].endswith("/refund")])
        console.cancel_reservation(res2.name)
        self.assertEqual(len([c for c in self.fake.calls if c[1].endswith("/refund")]), n_refund_calls)

    # ------------------------------------------------------------------ hold expiry policy
    def test_required_advance_hold_released(self):
        frappe.db.set_single_value(client.SETTINGS, "website_payment_policy", "Required")
        res = self.make_res(self.rooms[0], add_days(self.today, 3), add_days(self.today, 4))
        info = orders.website_advance_request(res.name)
        self.assertTrue(info["required"])
        frappe.db.set_value(TXN, info["transaction"], "hold_expires_on", add_to_date(now_datetime(), minutes=-1))
        payments.expire_and_release()
        self.assertEqual(frappe.db.get_value(TXN, info["transaction"], "status"), "Expired")
        self.assertEqual(frappe.db.get_value("Hotel Reservation", res.name, "status"), "Cancelled")
        # a paid reservation is never released
        res2 = self.make_res(self.rooms[1], add_days(self.today, 3), add_days(self.today, 4))
        info2 = orders.website_advance_request(res2.name)
        self.checkout(info2["url"].split("token=")[1])
        frappe.db.set_value(TXN, info2["transaction"], "hold_expires_on", add_to_date(now_datetime(), minutes=-1))
        payments.expire_and_release()
        self.assertEqual(frappe.db.get_value("Hotel Reservation", res2.name, "status"), "Reserved")

    def test_dashboard_data(self):
        res = self.make_res(self.rooms[0], add_days(self.today, 3), add_days(self.today, 4))
        txn, token = self.request_for(res, 60)
        self.checkout(token)
        data = api.get_dashboard_data({"hotel_reservation": res.name})
        self.assertEqual(data["totals"]["reconciled"], 1)
        self.assertEqual(data["amounts"]["captured"], 60)
        detail = api.get_transaction_detail(data["rows"][0]["name"])
        self.assertEqual(detail["payment_entry"], data["rows"][0]["payment_entry"])
