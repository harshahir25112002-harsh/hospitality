import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, getdate, date_diff, flt, cint


class OTABookingLog(Document):

	def validate(self):
		if self.check_in and self.check_out:
			self.nights = max(date_diff(self.check_out, self.check_in), 1)
		self.map_room_type()
		self.map_rate_plan()

	def map_room_type(self):
		"""Auto-map Channex Room Type ID to local Hotel Room Type."""
		if self.channex_room_type_id and not self.room_type:
			from hospitality_core.hospitality_core.doctype.ota_settings.ota_settings import get_local_room_type
			local_rt = get_local_room_type(self.channex_room_type_id)
			if local_rt:
				self.room_type = local_rt

	def map_rate_plan(self):
		"""Auto-map Channex Rate Plan ID to local Room Rate Plan."""
		if self.channex_rate_plan_id and not self.rate_plan:
			from hospitality_core.hospitality_core.doctype.ota_settings.ota_settings import get_local_rate_plan
			local_rp = get_local_rate_plan(self.channex_rate_plan_id)
			if local_rp:
				self.rate_plan = local_rp


@frappe.whitelist()
def process_booking_log(log_name):
	"""Manually trigger processing of an OTA Booking Log entry."""
	log = frappe.get_doc("OTA Booking Log", log_name)
	if log.status == "Processed" and log.reservation:
		frappe.msgprint(_("This booking has already been processed as {0}.").format(log.reservation))
		return {"status": "already_processed", "reservation": log.reservation}

	try:
		from hospitality_core.api.ota import create_reservation_from_log
		result = create_reservation_from_log(log)
		return result
	except Exception as e:
		log.status = "Failed"
		log.error_message = str(e)[:500]
		log.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.throw(str(e))

