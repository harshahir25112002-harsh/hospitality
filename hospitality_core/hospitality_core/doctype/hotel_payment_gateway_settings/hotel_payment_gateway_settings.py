import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from hospitality_core.integrations.razorpay.client import KEY_PREFIX


class HotelPaymentGatewaySettings(Document):
    def validate(self):
        if (self.environment or "Test") != "Test":
            frappe.throw(_("Live Mode cannot be activated from this form. Live activation is a separate, "
                           "Administrator-approved process and is not available in this release."))
        self.test_key_id = (self.test_key_id or "").strip()
        if self.test_key_id and not self.test_key_id.startswith(KEY_PREFIX["Test"]):
            frappe.throw(_("Test Mode Key ID must start with {0}. Live keys must never be entered here.").format(KEY_PREFIX["Test"]))
        if self.public_base_url:
            self.public_base_url = self.public_base_url.strip().rstrip("/")
            if not self.public_base_url.startswith(("https://", "http://")):
                frappe.throw(_("Public Base URL must start with https://"))
        if self.advance_type == "Percentage" and not (0 < flt(self.advance_value) <= 100):
            frappe.throw(_("Advance percentage must be between 0 and 100."))
        if self.advance_type == "Fixed Amount" and flt(self.advance_value) <= 0:
            frappe.throw(_("Fixed advance amount must be greater than zero."))
        if cint(self.pending_hold_minutes) < 5:
            self.pending_hold_minutes = 30
        if cint(self.link_expiry_minutes) < 10:
            self.link_expiry_minutes = 1440
        self.validate_accounting()
        if self.enabled:
            missing = [label for field, label in (("test_key_id", _("Key ID")), ("test_key_secret", _("Key Secret")),
                                                  ("company", _("Company")), ("clearing_account", _("Razorpay Clearing Account")),
                                                  ("mode_of_payment", _("Mode of Payment"))) if not self.get(field)]
            if missing:
                frappe.throw(_("Cannot enable the gateway. Missing: {0}").format(", ".join(missing)))
        before = self.get_doc_before_save()
        if before and (before.test_key_id != self.test_key_id or self.test_key_secret != before.test_key_secret):
            self.connection_status = _("Not tested")
            self.credentials_verified_for = None

    def validate_accounting(self):
        if self.clearing_account:
            acc = frappe.db.get_value("Account", self.clearing_account, ["company", "account_type", "is_group", "disabled"], as_dict=True)
            if not acc or acc.is_group or acc.disabled or acc.account_type not in ("Bank", "Cash"):
                frappe.throw(_("Razorpay Clearing Account must be an enabled Bank-type ledger (not a group)."))
            if self.company and acc.company != self.company:
                frappe.throw(_("Razorpay Clearing Account belongs to {0}, not {1}.").format(acc.company, self.company))
        if self.receivable_account:
            acc = frappe.db.get_value("Account", self.receivable_account, ["company", "account_type", "is_group"], as_dict=True)
            if not acc or acc.is_group or acc.account_type != "Receivable" or (self.company and acc.company != self.company):
                frappe.throw(_("Receivable Account must be a Receivable ledger of the selected company."))
        if self.mode_of_payment and not frappe.db.get_value("Mode of Payment", self.mode_of_payment, "enabled"):
            frappe.throw(_("Mode of Payment {0} is disabled.").format(self.mode_of_payment))
        if self.company and self.default_currency:
            cur = frappe.db.get_value("Company", self.company, "default_currency")
            if cur and cur != self.default_currency:
                frappe.throw(_("Default Currency must match the company currency ({0}).").format(cur))
