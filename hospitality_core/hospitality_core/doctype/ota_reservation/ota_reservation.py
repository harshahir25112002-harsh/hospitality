import frappe
from frappe.model.document import Document
from frappe.utils import date_diff


class OTAReservation(Document):

	def validate(self):
		if self.check_in_date and self.check_out_date:
			self.nights = max(date_diff(self.check_out_date, self.check_in_date), 1)

