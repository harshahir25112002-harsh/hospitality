"""Razorpay webhook processing.

1. Signature over the *raw* body with the Webhook Secret (not the API Key Secret).
2. Idempotency by X-Razorpay-Event-Id (fallback: SHA-256 of the body) in Hotel Payment Webhook Log
   (unique). Processed/ignored events are acknowledged without reprocessing; failed ones are retried.
3. The (signed) payment entity is applied through payments.process_payment, which is itself
   idempotent and order-independent (a late payment.failed never undoes a capture).
"""
import hashlib
import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from hospitality_core.integrations.razorpay import client, payments
from hospitality_core.integrations.razorpay.orders import TXN
from hospitality_core.integrations.razorpay.verification import verify_webhook_signature

LOG = "Hotel Payment Webhook Log"
HANDLED = ("payment.captured", "payment.failed", "payment.authorized", "order.paid")


class WebhookRejected(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _find_transaction(payment, order):
    order_id = (payment or {}).get("order_id") or (order or {}).get("id")
    if order_id:
        name = frappe.db.get_value(TXN, {"razorpay_order_id": order_id}, "name")
        if name:
            return name
    notes = (payment or {}).get("notes") or (order or {}).get("notes") or {}
    hint = notes.get("hotel_payment_transaction") if isinstance(notes, dict) else None
    if hint and frappe.db.get_value(TXN, hint, "razorpay_order_id") == order_id:
        return hint
    return None


def _log_start(event_id, event, payment_id, order_id):
    """Returns (log_name, should_process)."""
    existing = frappe.db.get_value(LOG, {"event_id": event_id}, ["name", "status"], as_dict=True)
    if existing:
        if existing.status == "Failed":
            frappe.db.set_value(LOG, existing.name, {"status": "Received", "received_on": now_datetime()})
            client.commit()
            return existing.name, True
        return existing.name, False
    frappe.db.savepoint("hc_rzp_log")
    try:
        doc = frappe.get_doc({"doctype": LOG, "event_id": event_id, "event": event, "status": "Received",
                              "razorpay_payment_id": payment_id, "razorpay_order_id": order_id, "received_on": now_datetime()})
        doc.flags.ignore_permissions = True
        doc.insert()
        client.commit()
        return doc.name, True
    except frappe.DuplicateEntryError:
        client.rollback_to("hc_rzp_log")
        return frappe.db.get_value(LOG, {"event_id": event_id}, "name"), False


def process(raw_body: bytes, signature, event_id_header):
    settings = client.get_settings()
    creds = client.get_credentials(settings, require_secret=False)
    if not creds.webhook_secret:
        raise WebhookRejected("webhook secret not configured", 503)
    if not verify_webhook_signature(raw_body, signature, creds.webhook_secret):
        raise WebhookRejected("invalid signature", 400)

    try:
        body = json.loads(raw_body)
    except ValueError:
        raise WebhookRejected("invalid payload", 400) from None
    event = str(body.get("event") or "")[:80]
    payload = body.get("payload") or {}
    payment = (payload.get("payment") or {}).get("entity") or {}
    order = (payload.get("order") or {}).get("entity") or {}
    event_id = (event_id_header or "").strip()[:140] or "sha256:" + hashlib.sha256(raw_body).hexdigest()

    frappe.db.set_single_value(client.SETTINGS, "last_webhook_received_on", now_datetime())
    log_name, should_process = _log_start(event_id, event, payment.get("id"), payment.get("order_id") or order.get("id"))
    if not should_process:
        return {"status": "duplicate"}

    result = {"status": "ignored"}
    frappe.db.savepoint("hc_rzp_webhook")
    try:
        txn = _find_transaction(payment, order) if event in HANDLED else None
        if event not in HANDLED:
            _finish(log_name, "Ignored", _("Event not used by Hospitality Core"))
        elif not txn:
            _finish(log_name, "Ignored", _("No matching Hotel Payment Transaction"))
        else:
            if event == "order.paid" and not payment:
                status = payments.sync_transaction(txn, settings)
            else:
                status = payments.process_payment(txn, payment, settings, origin="webhook")
            _finish(log_name, "Processed", _("Transaction status: {0}").format(status), txn)
            result = {"status": "processed"}
    except Exception as e:
        client.rollback_to("hc_rzp_webhook")
        frappe.log_error(title=f"Razorpay webhook processing failed ({event})")
        _finish(log_name, "Failed", str(e)[:300])
        raise WebhookRejected("processing failed, will be retried", 500) from None
    return result


def _finish(log_name, status, message, txn=None):
    frappe.db.set_value(LOG, log_name, {"status": status, "message": message, "transaction": txn})
    client.commit()
