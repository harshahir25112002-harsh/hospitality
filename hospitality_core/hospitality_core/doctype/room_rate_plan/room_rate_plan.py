import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate


class RoomRatePlan(Document):
    def validate(self):
        self.validate_dates()
        self.validate_commercial_terms()
        if self.active:
            self.validate_overlap()

    def validate_dates(self):
        if getdate(self.valid_from) > getdate(self.valid_to):
            frappe.throw(_("Valid From date cannot be after Valid To date."))

    def validate_commercial_terms(self):
        if not self.meal_plan:
            self.meal_plan = "Room Only"
        if not cint(self.is_refundable):
            self.free_cancellation = 0
            self.free_cancellation_hours = 0
        if cint(self.free_cancellation_hours) < 0:
            frappe.throw(_("Free cancellation hours cannot be negative."))
        for field in ("rate", "extra_adult_charge", "extra_child_charge", "extra_bed_charge"):
            if flt(self.get(field)) < 0:
                frappe.throw(_("{0} cannot be negative.").format(self.meta.get_label(field)))
        if not 0 <= flt(self.discount_percentage) <= 100:
            frappe.throw(_("Discount (%) must be between 0 and 100."))

    def validate_overlap(self):
        """
        Ensure no other Active rate plan exists for this Room Type
        and customer / customer_group within the overlapping date range.
        """
        conditions = [
            "room_type = %(room_type)s",
            "name != %(name)s",
            "active = 1",
            "valid_from <= %(valid_to)s",
            "valid_to >= %(valid_from)s",
            # plans with different meal plans / refundability are distinct products and may coexist
            "IFNULL(NULLIF(meal_plan, ''), 'Room Only') = %(meal_plan)s",
            "IFNULL(is_refundable, 1) = %(is_refundable)s",
        ]
        values = {
            "room_type": self.room_type,
            "name": self.name or "New Rate Plan",
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "meal_plan": self.meal_plan or "Room Only",
            "is_refundable": cint(self.is_refundable),
        }

        if self.customer:
            conditions.append("customer = %(customer)s")
            values["customer"] = self.customer
        else:
            conditions.append("(customer IS NULL OR customer = '')")

        if self.customer_group:
            conditions.append("customer_group = %(customer_group)s")
            values["customer_group"] = self.customer_group
        else:
            conditions.append("(customer_group IS NULL OR customer_group = '')")

        overlapping = frappe.db.sql(
            f"""
            SELECT name FROM `tabRoom Rate Plan`
            WHERE {" AND ".join(conditions)}
            """,
            values
        )

        if overlapping:
            frappe.throw(
                _("Rate Plan overlaps with existing active plan: {0} for Room Type {1}").format(
                    overlapping[0][0], self.room_type
                )
            )
