"""Refunds: explicitly initiated by Accounts Manager / System Manager only.

Nothing here runs automatically (no auto-refund on cancellation). A processed refund is booked as a
separate "Pay" Payment Entry (clearing account -> customer), the original receipt is never altered.
"""
import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime

from hospitality_core.integrations.razorpay import client
from hospitality_core.integrations.razorpay.orders import TXN
from hospitality_core.integrations.razorpay.reconciliation import _receivable, accounting_config, as_system_user
from hospitality_core.integrations.razorpay.verification import from_paise, to_paise

REFUND_ROLES = ("Accounts Manager", "System Manager")
REFUNDABLE = ("Reconciled", "Partially Refunded", "Refund Pending")
STATUS_MAP = {"pending": "Pending", "processed": "Processed", "failed": "Failed", "created": "Pending"}


def require_refund_role():
    if frappe.session.user != "Administrator" and not set(REFUND_ROLES) & set(frappe.get_roles()):
        frappe.throw(_("Only Accounts Managers can refund online payments."), frappe.PermissionError)


def refundable_amount(txn):
    reserved = sum(flt(r.amount) for r in txn.refunds if r.status in ("Pending", "Processed"))
    return flt(flt(txn.captured_amount) - reserved, 2)


def initiate_refund(txn_name, amount, reason):
    require_refund_role()
    settings = client.require_enabled()
    creds = client.get_credentials(settings)
    txn = frappe.get_doc(TXN, txn_name)
    if txn.status not in REFUNDABLE or not txn.razorpay_payment_id:
        frappe.throw(_("Only reconciled online payments can be refunded."))
    if not (reason or "").strip():
        frappe.throw(_("A refund reason is required."))
    amount = flt(amount, 2)
    available = refundable_amount(txn)
    if amount <= 0 or amount > available + 0.001:
        frappe.throw(_("Refund amount must be between 0 and {0}.").format(available))

    refund = client.create_refund(txn.razorpay_payment_id, to_paise(amount),
                                  {"hotel_payment_transaction": txn.name, "reason": reason[:200]}, f"{txn.name}-R{len(txn.refunds) + 1}",
                                  creds=creds)
    frappe.db.sql("SELECT name FROM `tabHotel Payment Transaction` WHERE name=%s FOR UPDATE", txn.name)
    txn.reload()
    txn.append("refunds", {
        "razorpay_refund_id": refund.get("id"), "amount": from_paise(refund.get("amount")), "currency": txn.currency,
        "status": STATUS_MAP.get(refund.get("status"), "Pending"), "reason": reason[:500],
        "requested_by": frappe.session.user, "requested_on": now_datetime(),
    })
    _apply(txn, settings)
    return txn.name


def sync_refunds(txn_name):
    settings = client.get_settings()
    creds = client.get_credentials(settings)
    txn = frappe.get_doc(TXN, txn_name)
    states = {}
    for r in txn.refunds:
        if r.status == "Pending" and r.razorpay_refund_id:
            states[r.razorpay_refund_id] = client.fetch_refund(txn.razorpay_payment_id, r.razorpay_refund_id, creds=creds)
    frappe.db.sql("SELECT name FROM `tabHotel Payment Transaction` WHERE name=%s FOR UPDATE", txn.name)
    txn.reload()
    for r in txn.refunds:
        if r.razorpay_refund_id in states:
            r.status = STATUS_MAP.get(states[r.razorpay_refund_id].get("status"), r.status)
    _apply(txn, settings)
    return txn.name


def _apply(txn, settings):
    for r in txn.refunds:
        if r.status == "Processed" and not r.payment_entry:
            r.payment_entry = _refund_entry(txn, r, settings)
    processed = flt(sum(flt(r.amount) for r in txn.refunds if r.status == "Processed"), 2)
    pending = any(r.status == "Pending" for r in txn.refunds)
    txn.refunded_amount = processed
    if pending:
        txn.status = "Refund Pending"
    elif processed >= flt(txn.captured_amount) - 0.001:
        txn.status = "Refunded"
    elif processed > 0:
        txn.status = "Partially Refunded"
    else:
        txn.status = "Reconciled"
    txn.flags.ignore_permissions = True
    txn.save()
    client.commit()


def _refund_entry(txn, row, settings):
    company = accounting_config(txn, settings)
    existing = frappe.db.get_value("Payment Entry", {"reference_no": row.razorpay_refund_id, "docstatus": 1,
                                                     "payment_type": "Pay"}, "name")
    if existing:
        return existing
    with as_system_user():
        pe = frappe.new_doc("Payment Entry")
        pe.update({
            "payment_type": "Pay", "company": company, "posting_date": getdate(),
            "party_type": "Customer", "party": txn.customer, "mode_of_payment": settings.mode_of_payment,
            "paid_from": settings.clearing_account, "paid_to": _receivable(txn, company, settings),
            "paid_amount": flt(row.amount), "received_amount": flt(row.amount),
            "reference_no": row.razorpay_refund_id, "reference_date": getdate(),
            "hotel_reservation": txn.hotel_reservation, "hotel_payment_transaction": txn.name,
            "remarks": _("Razorpay refund {0} of payment {1}: {2}").format(row.razorpay_refund_id, txn.razorpay_payment_id, row.reason or ""),
        })
        pe.flags.ignore_permissions = True
        pe.insert()
        pe.submit()
    return pe.name
