"""Guards that keep manual entries from impersonating verified online payments."""
import frappe
from frappe import _

OVERRIDE_ROLES = ("Accounts Manager", "System Manager")


def gateway_mode_of_payment():
    try:
        return frappe.db.get_single_value("Hotel Payment Gateway Settings", "mode_of_payment")
    except Exception:
        return None


def validate_payment_entry(doc, method=None):
    """Front-desk staff cannot record a 'Razorpay' receipt by hand: those Payment Entries are created only
    from verified, captured transactions. Accountants keep full control for corrections."""
    if doc.payment_type != "Receive" or doc.get("hotel_payment_transaction"):
        return
    mop = gateway_mode_of_payment()
    if not mop or doc.mode_of_payment != mop:
        return
    if frappe.session.user == "Administrator" or set(OVERRIDE_ROLES) & set(frappe.get_roles()):
        return
    frappe.throw(_("Online ({0}) payments are recorded automatically after Razorpay verification and cannot be entered manually.").format(mop))
