"""Payment state handling.

The only inputs that can move a transaction towards "paid" are payment entities that come either
from an authenticated Razorpay API call or from a webhook whose signature has been verified.
The browser checkout callback merely *triggers* a server-side fetch.
"""
import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime

from hospitality_core.integrations.razorpay import client, reconciliation
from hospitality_core.integrations.razorpay.orders import PAID, TXN
from hospitality_core.integrations.razorpay.verification import (
    check_payment_matches, from_paise, payment_summary, valid_id, verify_checkout_signature,
)

FINAL_FOR_FAILURE = PAID + ("Authorized",)


def _lock(name):
    frappe.db.sql("SELECT name FROM `tabHotel Payment Transaction` WHERE name=%s FOR UPDATE", name)
    return frappe.get_doc(TXN, name)


def _emit(txn_name):
    try:
        row = frappe.db.get_value(TXN, txn_name, ["name", "status", "hotel_reservation", "sales_invoice"], as_dict=True)
        frappe.publish_realtime("hotel_payment_update", row, after_commit=True)
        frappe.publish_realtime("hotel_console_update", {"type": "online_payment", "data": row}, after_commit=True)
    except Exception:
        pass


def process_payment(txn_name, payment, settings=None, creds=None, origin="api"):
    """Apply an *authentic* Razorpay payment entity to a transaction. Returns the transaction status."""
    settings = settings or client.get_settings()
    info = payment_summary(payment)
    txn = frappe.get_doc(TXN, txn_name)
    problems = check_payment_matches(payment, txn)
    if problems:
        frappe.db.set_value(TXN, txn.name, {"needs_review": 1, "review_note": _("Payment {0} ignored: {1}").format(
            info["id"], ", ".join(problems))})
        client.commit()
        return txn.status

    # authorized -> capture server-side for exactly the order amount (network call before any lock)
    if info["status"] == "authorized" and cint(settings.auto_capture) and txn.status not in PAID:
        try:
            payment = client.capture_payment(info["id"], info["amount"], info["currency"], creds=creds)
            info = payment_summary(payment)
        except client.RazorpayError as e:
            # e.g. already captured by auto-capture: re-read the authoritative state
            payment = client.fetch_payment(info["id"], creds=creds)
            info = payment_summary(payment)
            if info["status"] == "authorized":
                frappe.db.set_value(TXN, txn.name, {"status": "Authorized", "razorpay_payment_id": txn.razorpay_payment_id or info["id"],
                                                    "failure_reason": _("Capture failed: {0}").format(str(e)[:150])})
                client.commit()
                return "Authorized"

    txn = _lock(txn.name)
    status = info["status"]
    if status == "captured":
        if txn.razorpay_payment_id and txn.razorpay_payment_id != info["id"] and txn.status in PAID:
            # a second successful payment for the same order: never auto-post it, flag it
            frappe.db.set_value(TXN, txn.name, {"needs_review": 1, "review_note": _(
                "Additional captured payment {0} on the same order - review and refund if required.").format(info["id"])})
            client.commit()
            return txn.status
        if txn.status not in PAID:
            values = {
                "status": "Captured", "razorpay_payment_id": info["id"], "captured_amount": from_paise(info["amount"]),
                "captured_at": now_datetime(), "verified_at": txn.verified_at or now_datetime(),
                "payment_method": info["method"], "gateway_reference": info["reference"], "failure_reason": None,
            }
            if txn.status in ("Cancelled", "Expired"):
                values.update(needs_review=1, review_note=_("Paid after the request was {0}.").format(txn.status.lower()))
            frappe.db.set_value(TXN, txn.name, values)
        client.commit()
        reconciliation.reconcile(txn.name, settings)
        client.commit()
    elif status == "authorized":
        if txn.status not in PAID:
            frappe.db.set_value(TXN, txn.name, {"status": "Authorized", "razorpay_payment_id": info["id"],
                                                "payment_method": info["method"]})
        client.commit()
    elif status == "failed":
        if txn.status not in FINAL_FOR_FAILURE:  # out-of-order failed events never undo a success
            frappe.db.set_value(TXN, txn.name, {"status": "Failed",
                                                "failure_reason": info["error"] or _("Payment failed at the gateway.")})
        client.commit()
    else:  # created / refunded etc.: informational
        client.commit()
    _emit(txn.name)
    return frappe.db.get_value(TXN, txn.name, "status")


def verify_checkout(txn, order_id, payment_id, signature):
    """Browser checkout callback: verify the signature, then confirm the payment with the Razorpay API."""
    settings = client.require_enabled()
    creds = client.get_credentials(settings)
    if not (valid_id("order", order_id) and valid_id("payment", payment_id)):
        frappe.throw(_("Invalid payment response."))
    if order_id != txn.razorpay_order_id:
        frappe.throw(_("This payment does not belong to this payment request."))
    if not verify_checkout_signature(order_id, payment_id, signature, creds.secret):
        frappe.throw(_("Payment signature verification failed."))
    if txn.status not in PAID:
        frappe.db.set_value(TXN, txn.name, {"razorpay_signature": str(signature)[:140], "verified_at": now_datetime(),
                                            "status": "Payment Pending" if txn.status in ("Order Created", "Failed", "Initiated") else txn.status})
        client.commit()
    payment = client.fetch_payment(payment_id, creds=creds)  # independent confirmation, never the browser's word
    return process_payment(txn.name, payment, settings, creds, origin="checkout")


def sync_transaction(txn_name, settings=None):
    """Pull the authoritative state of an order from Razorpay (missed callbacks / webhooks)."""
    settings = settings or client.get_settings()
    txn = frappe.get_doc(TXN, txn_name)
    if txn.status in ("Captured", "Reconciliation Pending") and not txn.payment_entry:
        reconciliation.reconcile(txn.name, settings)
        client.commit()
        return frappe.db.get_value(TXN, txn.name, "status")
    if not txn.razorpay_order_id or txn.status in ("Reconciled", "Refunded", "Partially Refunded", "Refund Pending"):
        return txn.status
    creds = client.get_credentials(settings)
    items = client.fetch_order_payments(txn.razorpay_order_id, creds=creds)
    rank = {"captured": 3, "authorized": 2, "failed": 1}
    items = sorted(items, key=lambda p: (rank.get(p.get("status"), 0), p.get("created_at") or 0), reverse=True)
    if items:
        return process_payment(txn.name, items[0], settings, creds, origin="sync")
    return txn.status


def sync_if_stale(txn, seconds=8):
    """Throttled sync for status polling: at most one Razorpay call per transaction per `seconds`."""
    if txn.status in ("Reconciled", "Cancelled", "Expired", "Refunded") or not txn.razorpay_order_id:
        return txn.status
    key = f"hc_rzp_sync:{txn.name}"
    if not frappe.cache.set(frappe.cache.make_key(key), 1, nx=True, ex=seconds):
        return txn.status
    try:
        return sync_transaction(txn.name)
    except client.RazorpayError:
        return txn.status


def expire_and_release():
    """Scheduler (every 5 min): expire stale requests, release unpaid website holds, retry reconciliation."""
    settings = client.get_settings()
    if not settings.enabled:
        return
    now = now_datetime()
    stale = frappe.get_all(TXN, filters={"status": ["in", ("Initiated", "Order Created", "Payment Pending", "Failed", "Authorized")]},
                           fields=["name", "expires_on", "hold_expires_on", "hotel_reservation", "razorpay_order_id"])
    for row in stale:
        hold_over = row.hold_expires_on and get_datetime(row.hold_expires_on) < now
        link_over = row.expires_on and get_datetime(row.expires_on) < now
        if not (hold_over or link_over):
            continue
        frappe.db.savepoint("hc_rzp_expire")
        try:
            status = sync_transaction(row.name, settings) if row.razorpay_order_id else "Initiated"
            if status in PAID or status == "Authorized":
                continue
            frappe.db.set_value(TXN, row.name, {"status": "Expired"})
            if hold_over and row.hotel_reservation:
                release_unpaid_hold(row.hotel_reservation, row.name)
            client.commit()
        except Exception:
            client.rollback_to("hc_rzp_expire")
            frappe.log_error(title=f"Razorpay expiry check failed: {row.name}")
    for name in frappe.get_all(TXN, filters={"status": ["in", ("Captured", "Reconciliation Pending")],
                                             "payment_entry": ["is", "not set"], "scenario": ["!=", "Gateway Test"]}, pluck="name"):
        try:
            reconciliation.reconcile(name, settings)
            client.commit()
        except Exception:
            frappe.log_error(title=f"Razorpay scheduled reconciliation failed: {name}")


def release_unpaid_hold(reservation, txn_name):
    """Cancel a website reservation whose required advance was not paid in time (existing cancel flow)."""
    from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import cancel_reservation
    status = frappe.db.get_value("Hotel Reservation", reservation, "status")
    if status != "Reserved":
        return
    paid = frappe.db.count("Payment Entry", {"hotel_reservation": reservation, "docstatus": 1, "payment_type": "Receive"})
    open_online = frappe.db.count(TXN, {"hotel_reservation": reservation, "status": ["in", PAID + ("Authorized",)]})
    if paid or open_online:
        return
    with reconciliation.as_system_user():
        cancel_reservation(reservation)
        frappe.get_doc("Hotel Reservation", reservation).add_comment(
            "Comment", _("Cancelled automatically: required online advance ({0}) was not paid within the hold period.").format(txn_name))
