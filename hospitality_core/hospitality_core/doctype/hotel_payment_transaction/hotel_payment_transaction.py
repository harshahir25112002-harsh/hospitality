import frappe
from frappe import _
from frappe.model.document import Document


class HotelPaymentTransaction(Document):
    """Created and updated only by hospitality_core.integrations.razorpay (all fields are read-only).
    Status can never be set to a paid state by a user: see payments.process_payment."""

    def on_trash(self):
        if self.razorpay_payment_id or self.payment_entry:
            frappe.throw(_("Transactions with a Razorpay payment cannot be deleted."))
