"""Whitelisted Razorpay endpoints.

Guest (token-bound, rate-limited):  get_payment_context, create_order, verify_payment,
                                    report_checkout_event, get_payment_status
Webhook (signature-bound):          handle_webhook
Staff (console roles):              create_reservation_payment_request, create_invoice_payment_request,
                                    get_transaction_status, cancel_payment_request, get_online_payments
Gateway admin:                      get_gateway_status, test_connection, verify_credentials,
                                    generate_test_payment, get_webhook_info, disable_gateway,
                                    setup_accounting_defaults
Dashboard:                          get_dashboard_data, get_transaction_detail, retry_reconciliation,
                                    sync_transaction, refund_transaction, sync_refunds
"""
import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import add_days, cint, flt, getdate, now_datetime

from hospitality_core.integrations.razorpay import client, orders, payments, reconciliation, refunds, webhooks
from hospitality_core.integrations.razorpay.orders import PAID, TXN

GATEWAY_ADMIN_ROLES = ("System Manager", "Accounts Manager")
STAFF_ROLES = ("Hospitality User", "Hospitality Manager", "System Manager", "Accounts User", "Accounts Manager")
WEBHOOK_EVENTS = ["payment.captured", "payment.failed", "order.paid"]


def _require(roles):
    if frappe.session.user == "Administrator":
        return
    if not set(roles) & set(frappe.get_roles()):
        frappe.throw(_("Not permitted."), frappe.PermissionError)


def _staff_view(txn):
    return {
        "name": txn.name, "status": txn.status, "scenario": txn.scenario, "amount": txn.amount, "currency": txn.currency,
        "hotel_reservation": txn.hotel_reservation, "sales_invoice": txn.sales_invoice, "customer": txn.customer,
        "customer_name": txn.customer_name, "payment_entry": txn.payment_entry, "razorpay_order_id": txn.razorpay_order_id,
        "razorpay_payment_id": txn.razorpay_payment_id, "payment_method": txn.payment_method,
        "failure_reason": txn.failure_reason, "needs_review": txn.needs_review, "review_note": txn.review_note,
        "expires_on": txn.expires_on, "creation": txn.creation, "environment": txn.environment,
    }


def _handoff(txn, token):
    url = orders.pay_url(token)
    return {"transaction": _staff_view(txn), "pay_url": url, "qr_svg": _qr_svg(url)}


def _qr_svg(text):
    try:
        import io

        import pyqrcode
        buf = io.BytesIO()
        pyqrcode.create(text, error="M").svg(buf, scale=4, xmldecl=False, svgns=True, module_color="#111")
        return buf.getvalue().decode()
    except Exception:
        return None


# =========================================================================== guest checkout
@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=60, seconds=60)
def get_payment_context(token):
    txn = orders.get_txn_by_token(token)
    return orders.public_context(txn)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=600)
def create_order(token):
    txn = orders.get_txn_by_token(token, for_payment=True)
    if txn.status in PAID:
        return orders.public_context(txn)
    try:
        txn = orders.ensure_order(txn)
    except client.RazorpayError as e:
        frappe.log_error(title=f"Razorpay order creation failed: {txn.name}", message=str(e))
        frappe.throw(_("The payment could not be started. Please try again in a moment."))
    return orders.public_context(txn, include_checkout=True)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=30, seconds=600)
def verify_payment(token, razorpay_order_id=None, razorpay_payment_id=None, razorpay_signature=None):
    txn = orders.get_txn_by_token(token)
    try:
        payments.verify_checkout(txn, razorpay_order_id, razorpay_payment_id, razorpay_signature)
    except client.RazorpayError:
        # payment state could not be confirmed right now; the webhook / status poll will settle it
        pass
    return orders.public_context(frappe.get_doc(TXN, txn.name))


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=30, seconds=600)
def report_checkout_event(token, event=None):
    """Checkout reported a failure or was closed. The browser's word is not trusted: we only
    re-read the order from Razorpay."""
    txn = orders.get_txn_by_token(token)
    if txn.razorpay_order_id and txn.status not in PAID:
        try:
            payments.sync_transaction(txn.name)
        except client.RazorpayError:
            pass
    return orders.public_context(frappe.get_doc(TXN, txn.name))


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=120, seconds=60)
def get_payment_status(token):
    txn = orders.get_txn_by_token(token)
    payments.sync_if_stale(txn)
    return orders.public_context(frappe.get_doc(TXN, txn.name))


# =========================================================================== webhook
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=600, seconds=60)
def handle_webhook():
    req = frappe.request
    raw = req.get_data(cache=True) or b""
    try:
        result = webhooks.process(raw, req.headers.get("X-Razorpay-Signature"), req.headers.get("X-Razorpay-Event-Id"))
    except webhooks.WebhookRejected as e:
        frappe.local.response["http_status_code"] = e.status
        return {"status": "rejected", "reason": str(e)}
    except client.GatewayDisabled:
        frappe.local.response["http_status_code"] = 503
        return {"status": "rejected", "reason": "gateway not configured"}
    return result


# =========================================================================== staff
@frappe.whitelist(methods=["POST"])
@rate_limit(limit=60, seconds=600)
def create_reservation_payment_request(reservation, amount=None, idempotency_key=None):
    _require(STAFF_ROLES)
    txn, token = orders.front_desk_request(reservation, amount, idempotency_key)
    client.commit()
    return _handoff(txn, token)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=60, seconds=600)
def create_invoice_payment_request(sales_invoice, amount=None, idempotency_key=None):
    _require(STAFF_ROLES)
    if not frappe.has_permission("Sales Invoice", "read", sales_invoice):
        frappe.throw(_("Not permitted."), frappe.PermissionError)
    txn, token = orders.invoice_request(sales_invoice, amount, idempotency_key)
    client.commit()
    return _handoff(txn, token)


@frappe.whitelist()
def get_transaction_status(name):
    _require(STAFF_ROLES)
    txn = frappe.get_doc(TXN, name)
    payments.sync_if_stale(txn)
    return _staff_view(frappe.get_doc(TXN, name))


@frappe.whitelist(methods=["POST"])
def cancel_payment_request(name):
    _require(STAFF_ROLES)
    txn = frappe.get_doc(TXN, name)
    if txn.status not in ("Initiated", "Order Created", "Payment Pending", "Failed"):
        frappe.throw(_("Only unpaid payment requests can be cancelled."))
    if txn.razorpay_order_id:  # never cancel something that was actually paid a second ago
        try:
            if payments.sync_transaction(txn.name) in PAID:
                return _staff_view(frappe.get_doc(TXN, name))
        except client.RazorpayError:
            pass
    frappe.db.set_value(TXN, name, {"status": "Cancelled", "failure_reason": _("Cancelled by {0}").format(frappe.session.user)})
    return _staff_view(frappe.get_doc(TXN, name))


@frappe.whitelist()
def get_online_payments(reservation=None, sales_invoice=None):
    _require(STAFF_ROLES)
    filters = {"hotel_reservation": reservation} if reservation else {"sales_invoice": sales_invoice}
    if not (reservation or sales_invoice):
        return []
    return frappe.get_all(TXN, filters=filters, order_by="creation desc", limit=20,
                          fields=["name", "status", "amount", "currency", "razorpay_payment_id", "payment_entry",
                                  "payment_method", "creation", "scenario", "failure_reason", "needs_review"])


@frappe.whitelist()
def get_front_desk_config():
    _require(STAFF_ROLES)
    s = client.get_settings()
    return {"enabled": bool(s.enabled), "front_desk": bool(s.enabled and cint(s.allow_front_desk)),
            "invoice": bool(s.enabled and cint(s.allow_invoice_payment)), "mode_of_payment": s.mode_of_payment,
            "environment": s.environment}


# =========================================================================== gateway admin
def _webhook_url(s=None):
    return f"{orders.public_base_url(s)}/api/method/hospitality_core.api.razorpay.handle_webhook"


@frappe.whitelist()
def get_gateway_status():
    _require(GATEWAY_ADMIN_ROLES)
    s = client.get_settings()
    env = s.environment or "Test"
    count = lambda **f: frappe.db.count(TXN, {"environment": env, **f})
    key_ok = bool(s.test_key_id and s.test_key_secret)
    steps = [
        {"key": "credentials", "label": _("API credentials configured"), "done": key_ok},
        {"key": "connection", "label": _("Test connection successful"),
         "done": bool(s.credentials_verified_for and s.credentials_verified_for == s.test_key_id)},
        {"key": "webhook_secret", "label": _("Webhook secret configured"), "done": bool(s.test_webhook_secret)},
        {"key": "webhook", "label": _("Webhook endpoint registered (valid webhook received)"), "done": bool(s.last_webhook_received_on)},
        {"key": "payment", "label": _("Test payment successful"), "done": count(status=["in", PAID]) > 0},
        {"key": "reconciliation", "label": _("Payment Entry reconciliation successful"),
         "done": count(payment_entry=["is", "set"]) > 0},
    ]
    accounting_ok = bool(s.company and s.clearing_account and s.mode_of_payment)
    return {
        "enabled": bool(s.enabled), "environment": env, "gateway": "Razorpay",
        "key_id_masked": (s.test_key_id[:9] + "…" + s.test_key_id[-4:]) if s.test_key_id and len(s.test_key_id) > 14 else (s.test_key_id or ""),
        "key_configured": key_ok, "webhook_secret_configured": bool(s.test_webhook_secret),
        "accounting_configured": accounting_ok,
        "connection_status": s.connection_status or _("Not tested"), "last_connection_test_on": s.last_connection_test_on,
        "last_webhook_received_on": s.last_webhook_received_on, "last_successful_payment_on": s.last_successful_payment_on,
        "total_transactions": count(), "failed_transactions": count(status="Failed"),
        "captured_transactions": count(status=["in", PAID]),
        "pending_reconciliation": count(status=["in", ("Captured", "Reconciliation Pending")], scenario=["!=", "Gateway Test"]),
        "webhook_url": _webhook_url(s), "webhook_events": WEBHOOK_EVENTS,
        "https": orders.public_base_url(s).startswith("https://"),
        "steps": steps, "progress": round(100 * sum(1 for x in steps if x["done"]) / len(steps)),
    }


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=20, seconds=600)
def test_connection():
    _require(GATEWAY_ADMIN_ROLES)
    s = client.get_settings()
    ok, message = False, ""
    try:
        creds = client.get_credentials(s)
        client.ping(creds)
        ok, message = True, _("Connected to Razorpay {0} Mode as {1}.").format(creds.environment, s.test_key_id[:13] + "…")
    except client.RazorpayError as e:
        message = str(e)
    except client.GatewayDisabled as e:
        message = str(e)
    frappe.db.set_single_value(client.SETTINGS, {
        "connection_status": (_("Connected") if ok else _("Failed")) + f" ({now_datetime():%Y-%m-%d %H:%M})",
        "last_connection_test_on": now_datetime(),
        "credentials_verified_for": s.test_key_id if ok else None,
    })
    return {"ok": ok, "message": message}


@frappe.whitelist()
def verify_credentials():
    """Local checks only (format / environment isolation / presence); no secret is returned."""
    _require(GATEWAY_ADMIN_ROLES)
    s = client.get_settings()
    checks = []
    add = lambda label, ok, hint="": checks.append({"label": label, "ok": bool(ok), "hint": hint})
    add(_("Environment is Test Mode"), (s.environment or "Test") == "Test")
    add(_("Key ID present"), s.test_key_id)
    add(_("Key ID is a Test Mode key (rzp_test_…)"), (s.test_key_id or "").startswith("rzp_test_"),
        _("Live keys (rzp_live_…) are rejected in Test Mode."))
    add(_("Key Secret stored (encrypted)"), s.test_key_secret)
    add(_("Webhook Secret stored (encrypted)"), s.test_webhook_secret, _("Required to accept webhooks."))
    secret = s.get_password("test_key_secret", raise_exception=False) if s.test_key_secret else ""
    wsecret = s.get_password("test_webhook_secret", raise_exception=False) if s.test_webhook_secret else ""
    add(_("Webhook Secret differs from API Key Secret"), not (secret and wsecret and secret == wsecret),
        _("Use a separate secret for the webhook."))
    add(_("Accounting configured (Company, Clearing Account, Mode of Payment)"),
        s.company and s.clearing_account and s.mode_of_payment)
    return {"ok": all(c["ok"] for c in checks[:4]), "checks": checks}


@frappe.whitelist(methods=["POST"])
def generate_test_payment(amount=1):
    _require(GATEWAY_ADMIN_ROLES)
    txn, token = orders.gateway_test_request(amount)
    client.commit()
    return _handoff(txn, token)


@frappe.whitelist()
def get_webhook_info():
    _require(GATEWAY_ADMIN_ROLES)
    s = client.get_settings()
    return {"url": _webhook_url(s), "events": WEBHOOK_EVENTS, "secret_configured": bool(s.test_webhook_secret),
            "last_received": s.last_webhook_received_on, "https": _webhook_url(s).startswith("https://")}


@frappe.whitelist(methods=["POST"])
def disable_gateway():
    _require(GATEWAY_ADMIN_ROLES)
    frappe.db.set_single_value(client.SETTINGS, "enabled", 0)
    return {"enabled": False}


@frappe.whitelist(methods=["POST"])
def setup_accounting_defaults(company):
    """Explicit, admin-triggered helper: create a 'Razorpay Clearing' Bank ledger and a 'Razorpay'
    Mode of Payment for the company if they do not exist. Existing records are never modified."""
    _require(GATEWAY_ADMIN_ROLES)
    abbr = frappe.db.get_value("Company", company, "abbr")
    if not abbr:
        frappe.throw(_("Company {0} not found.").format(company))
    parent = frappe.db.get_value("Account", {"company": company, "is_group": 1, "account_type": "Bank"}, "name") \
        or frappe.db.get_value("Account", {"company": company, "is_group": 1, "account_name": "Bank Accounts"}, "name")
    if not parent:
        frappe.throw(_("No Bank Accounts group found in the Chart of Accounts of {0}.").format(company))
    account = f"Razorpay Clearing - {abbr}"
    if not frappe.db.exists("Account", account):
        frappe.get_doc({"doctype": "Account", "account_name": "Razorpay Clearing", "company": company,
                        "parent_account": parent, "account_type": "Bank", "is_group": 0}).insert()
    mop = "Razorpay"
    if not frappe.db.exists("Mode of Payment", mop):
        frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": mop, "type": "Bank", "enabled": 1,
                        "accounts": [{"company": company, "default_account": account}]}).insert()
    elif not frappe.db.exists("Mode of Payment Account", {"parent": mop, "company": company}):
        doc = frappe.get_doc("Mode of Payment", mop)
        doc.append("accounts", {"company": company, "default_account": account})
        doc.save()
    return {"clearing_account": account, "mode_of_payment": mop,
            "currency": frappe.db.get_value("Company", company, "default_currency")}


# =========================================================================== dashboard
@frappe.whitelist()
def get_dashboard_data(filters=None):
    _require(STAFF_ROLES)
    f = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
    cond = {}
    if f.get("from_date") or f.get("to_date"):
        cond["creation"] = ["between", [getdate(f.get("from_date") or "2000-01-01"), add_days(getdate(f.get("to_date") or None), 1)]]
    for key in ("customer", "hotel_reservation", "status", "environment", "scenario"):
        if f.get(key):
            cond[key] = f[key]
    if f.get("razorpay_payment_id"):
        cond["razorpay_payment_id"] = ["like", f"%{f['razorpay_payment_id'].strip()}%"]
    if f.get("min_amount"):
        cond["amount"] = [">=", flt(f["min_amount"])]
    if f.get("max_amount"):
        cond.setdefault("amount", None)
        cond["amount"] = ["between", [flt(f.get("min_amount") or 0), flt(f["max_amount"])]]
    rows = frappe.get_all(TXN, filters=cond, order_by="creation desc", limit=min(cint(f.get("limit") or 200), 1000),
                          fields=["name", "creation", "status", "scenario", "environment", "amount", "currency", "customer",
                                  "customer_name", "hotel_reservation", "sales_invoice", "razorpay_order_id",
                                  "razorpay_payment_id", "payment_entry", "payment_method", "needs_review"])
    totals = {"initiated": 0, "captured": 0, "failed": 0, "pending": 0, "refunded": 0, "reconciled": 0}
    amounts = dict.fromkeys(totals, 0.0)

    def bump(k, amt):
        totals[k] += 1
        amounts[k] = flt(amounts[k] + flt(amt), 2)

    for r in rows:
        bump("initiated", r.amount)
        if r.status in PAID:
            bump("captured", r.amount)
        if r.status == "Failed":
            bump("failed", r.amount)
        if r.status in ("Initiated", "Order Created", "Payment Pending", "Authorized", "Captured", "Reconciliation Pending"):
            bump("pending", r.amount)
        if r.status in ("Refunded", "Partially Refunded", "Refund Pending"):
            bump("refunded", r.amount)
        if r.payment_entry:
            bump("reconciled", r.amount)
    return {"rows": rows, "totals": totals, "amounts": amounts,
            "can_refund": frappe.session.user == "Administrator" or bool(set(refunds.REFUND_ROLES) & set(frappe.get_roles()))}


@frappe.whitelist()
def get_transaction_detail(name):
    _require(STAFF_ROLES)
    txn = frappe.get_doc(TXN, name)
    data = _staff_view(txn)
    data.update({"captured_amount": txn.captured_amount, "refunded_amount": txn.refunded_amount,
                 "gateway_reference": txn.gateway_reference, "created_at": txn.created_at, "verified_at": txn.verified_at,
                 "captured_at": txn.captured_at, "reconciled_at": txn.reconciled_at, "source": txn.source,
                 "refunds": [r.as_dict() for r in txn.refunds],
                 "refundable": refunds.refundable_amount(txn) if txn.status in refunds.REFUNDABLE else 0,
                 "webhooks": frappe.get_all(webhooks.LOG, filters={"transaction": name}, order_by="creation asc",
                                            fields=["event", "status", "received_on", "message"])})
    return data


@frappe.whitelist(methods=["POST"])
def retry_reconciliation(name):
    """Only for captured payments without an accounting document. Never marks anything as paid."""
    _require(STAFF_ROLES)
    txn = frappe.get_doc(TXN, name)
    if txn.status not in ("Captured", "Reconciliation Pending") or txn.payment_entry:
        frappe.throw(_("Only captured payments without a Payment Entry can be reconciled."))
    pe = reconciliation.reconcile(name)
    client.commit()
    return {"payment_entry": pe, "status": frappe.db.get_value(TXN, name, "status"),
            "failure_reason": frappe.db.get_value(TXN, name, "failure_reason")}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=60, seconds=600)
def sync_transaction(name):
    _require(STAFF_ROLES)
    status = payments.sync_transaction(name)
    return {"status": status}


@frappe.whitelist(methods=["POST"])
def refund_transaction(name, amount, reason):
    refunds.require_refund_role()
    refunds.initiate_refund(name, amount, reason)
    return get_transaction_detail(name)


@frappe.whitelist(methods=["POST"])
def sync_refunds(name):
    refunds.require_refund_role()
    refunds.sync_refunds(name)
    return get_transaction_detail(name)
