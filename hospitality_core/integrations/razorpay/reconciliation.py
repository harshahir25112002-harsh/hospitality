"""Captured Razorpay payment -> exactly one standard ERPNext Payment Entry.

* Runs under a row lock on the transaction, after every network call has finished.
* Idempotent: a transaction that already has a Payment Entry, or a Payment Entry that already carries
  the Razorpay payment id, is never posted twice. Unique keys on the transaction back this up.
* Uses Payment Entry insert()/submit() only: ERPNext validates and posts the GL itself.
* Funds go to the configured Razorpay clearing account (captured != settled to bank).
"""
import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime

from hospitality_core.integrations.razorpay import client
from hospitality_core.integrations.razorpay.client import as_system_user  # noqa: F401 (re-exported)

TXN = "Hotel Payment Transaction"
RECONCILABLE = ("Captured", "Reconciliation Pending")


def _lock(name):
    frappe.db.sql("SELECT name FROM `tabHotel Payment Transaction` WHERE name=%s FOR UPDATE", name)
    return frappe.get_doc(TXN, name)


def accounting_config(txn, settings):
    company = txn.company or settings.company or frappe.db.get_single_value("Hotel Settings", "company")
    if not settings.clearing_account:
        frappe.throw(_("Razorpay Clearing Account is not set in Payment Gateway settings."))
    if not settings.mode_of_payment:
        frappe.throw(_("Razorpay Mode of Payment is not set in Payment Gateway settings."))
    acc = frappe.db.get_value("Account", settings.clearing_account, ["company", "account_type", "is_group"], as_dict=True)
    if not acc or acc.company != company or acc.is_group or acc.account_type not in ("Bank", "Cash"):
        frappe.throw(_("Razorpay Clearing Account must be a Bank/Cash ledger of company {0}.").format(company))
    return company


def _receivable(txn, company, settings):
    if txn.sales_invoice:
        return frappe.db.get_value("Sales Invoice", txn.sales_invoice, "debit_to")
    if settings.receivable_account:
        return settings.receivable_account
    from erpnext.accounts.party import get_party_account
    return get_party_account("Customer", txn.customer, company)


def build_payment_entry(txn, settings):
    company = accounting_config(txn, settings)
    amount = flt(txn.captured_amount or txn.amount, 2)
    pe = frappe.new_doc("Payment Entry")
    pe.update({
        "payment_type": "Receive",
        "company": company,
        "posting_date": getdate(),
        "party_type": "Customer",
        "party": txn.customer,
        "mode_of_payment": settings.mode_of_payment,
        "paid_from": _receivable(txn, company, settings),
        "paid_to": settings.clearing_account,
        "paid_amount": amount,
        "received_amount": amount,
        "reference_no": txn.razorpay_payment_id,
        "reference_date": getdate(txn.captured_at) if txn.captured_at else getdate(),
        "hotel_reservation": txn.hotel_reservation,
        "razorpay_payment_id": txn.razorpay_payment_id,
        "hotel_payment_transaction": txn.name,
        "remarks": _("Razorpay {0} payment {1} (order {2}) for {3}").format(
            txn.environment, txn.razorpay_payment_id, txn.razorpay_order_id,
            txn.sales_invoice or txn.hotel_reservation or txn.name),
    })
    if txn.sales_invoice:
        outstanding = flt(frappe.db.get_value("Sales Invoice", txn.sales_invoice, "outstanding_amount"))
        allocate = min(amount, max(outstanding, 0))
        if allocate > 0:  # any excess stays as an unallocated customer advance, never altering the invoice
            pe.append("references", {"reference_doctype": "Sales Invoice", "reference_name": txn.sales_invoice,
                                     "allocated_amount": allocate})
    return pe  # insert() runs ERPNext's own validate: party account, exchange rates, ref details, amounts


def _existing_entry(payment_id):
    return frappe.db.get_value("Payment Entry", {"razorpay_payment_id": payment_id, "docstatus": ["<", 2]}, "name")


def reconcile(txn_name, settings=None):
    """Create (or link) the Payment Entry for a captured transaction. Returns the Payment Entry name or None."""
    settings = settings or client.get_settings()
    txn = _lock(txn_name)
    if txn.payment_entry:
        return txn.payment_entry
    if txn.scenario == "Gateway Test" or txn.status not in RECONCILABLE or not txn.razorpay_payment_id:
        return None
    if not txn.customer:
        _mark_pending(txn, _("Transaction has no Customer."))
        return None

    frappe.db.savepoint("hc_rzp_reconcile")
    try:
        with as_system_user():
            pe_name = _existing_entry(txn.razorpay_payment_id)
            if pe_name:
                pe = frappe.get_doc("Payment Entry", pe_name)
                if pe.docstatus == 0:
                    pe.submit()
            else:
                pe = build_payment_entry(txn, settings)
                pe.flags.ignore_permissions = True
                pe.insert()
                pe.submit()
    except Exception as e:
        client.rollback_to("hc_rzp_reconcile")
        frappe.log_error(title=f"Razorpay reconciliation failed: {txn.name}")
        _mark_pending(txn, _("Payment Entry could not be created: {0}").format(str(e)[:200]))
        return None

    note = None
    if txn.hotel_reservation and frappe.db.get_value("Hotel Reservation", txn.hotel_reservation, "status") == "Cancelled":
        note = _("Payment received for a cancelled reservation - review for refund.")
    frappe.db.set_value(TXN, txn.name, {
        "payment_entry": pe.name, "status": "Reconciled", "reconciled_at": now_datetime(), "failure_reason": None,
        **({"needs_review": 1, "review_note": note} if note else {}),
    })
    frappe.db.set_single_value(client.SETTINGS, "last_successful_payment_on", now_datetime())
    _refresh_reservation(txn.hotel_reservation)
    return pe.name


def _mark_pending(txn, reason):
    frappe.db.set_value(TXN, txn.name, {"status": "Reconciliation Pending", "failure_reason": reason})


def _refresh_reservation(reservation):
    if not reservation:
        return
    try:
        from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import get_billing_summary
        if frappe.db.get_value("Hotel Reservation", reservation, "status") != "Cancelled":
            with as_system_user():
                get_billing_summary(reservation)
    except Exception:
        frappe.log_error(title=f"Billing refresh after Razorpay payment failed: {reservation}")
