"""
Acceptance tests for OTA (Channex) integration:
- Webhook payload processing
- Auto-creation of Customer and Hotel Reservation
- Duplicate booking prevention
- Modification and cancellation of OTA reservations
- Acknowledgment handling
- OTA Booking Log state machine
"""
import json
import frappe
from frappe.utils import add_days, nowdate
from unittest import mock

from hospitality_core.constants import ReservationStatus
from hospitality_core.api import ota
from hospitality_core.tests import test_flow


class TestOTAIntegration(test_flow.TestHotelFlow):
	def test_complete_hotel_lifecycle(self):
		self.skipTest("covered by TestHotelFlow")

	def test_pos_scenarios_a_to_g(self):
		self.skipTest("covered by TestHotelFlow")

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

		# Ensure OTA Settings is configured for testing
		ota_settings = frappe.get_single("OTA Settings")
		ota_settings.enabled = 1
		ota_settings.environment = "Staging"
		ota_settings.api_base_url = "https://staging.channex.io/api/v1"
		ota_settings.channex_property_id = "test-prop-uuid"
		ota_settings.auto_create_reservation = 1
		ota_settings.auto_acknowledge = 1
		ota_settings.auto_sync_availability = 0  # don't make real network calls in unit tests
		ota_settings.auto_sync_rates = 0

		# Map room type
		ota_settings.set("room_type_map", [])
		ota_settings.append("room_type_map", {
			"room_type": self.room_type,
			"channex_room_type_id": "channex-deluxe-uuid",
			"channex_room_type_name": "Deluxe Room",
			"is_synced": 1
		})
		ota_settings.save(ignore_permissions=True)

	def test_ota_new_booking_webhook(self):
		"""Simulate an incoming booking from MakeMyTrip / Channex."""
		booking_id = "MMT-TEST-" + frappe.generate_hash(length=8)
		payload = {
			"event": "booking",
			"payload": {
				"id": "rev-101",
				"ota_reservation_code": booking_id,
				"ota_name": "MakeMyTrip",
				"status": "new",
				"arrival_date": nowdate(),
				"departure_date": add_days(nowdate(), 2),
				"customer": {
					"name": "Rahul",
					"surname": "Sharma",
					"email": "rahul.sharma@example.com",
					"phone": "+919876543210"
				},
				"rooms": [
					{
						"room_type_id": "channex-deluxe-uuid",
						"occupancy": {"adults": 2, "children": 0}
					}
				],
				"total_price": 5000.0,
				"currency": "INR",
				"commission": 500.0,
				"payment_status": "prepaid",
				"payment_collect": "OTA"
			}
		}

		with mock.patch("hospitality_core.api.ota.acknowledge_booking_revision", return_value=True):
			res = ota.handle_booking_revision_record(payload["payload"], raw_data=json.dumps(payload))

		self.assertIsNotNone(res)
		log = frappe.get_doc("OTA Booking Log", res["log"])
		self.assertEqual(log.ota_booking_id, booking_id)
		self.assertEqual(log.ota_source, "MakeMyTrip")
		self.assertEqual(log.status, "Processed")
		self.assertTrue(log.reservation)

		# Verify Hotel Reservation
		hr = frappe.get_doc("Hotel Reservation", log.reservation)
		self.assertEqual(hr.status, ReservationStatus.RESERVED)
		self.assertEqual(hr.room_type, self.room_type)
		self.assertEqual(hr.ota_source, "MakeMyTrip")
		self.assertEqual(hr.ota_booking_id, booking_id)
		self.assertEqual(hr.ota_commission, 500.0)

	def test_ota_duplicate_prevention(self):
		"""Same booking ID received twice must update the existing log rather than duplicate."""
		booking_id = "BOOKINGCOM-" + frappe.generate_hash(length=8)
		payload = {
			"id": "rev-201",
			"ota_reservation_code": booking_id,
			"ota_name": "Booking.com",
			"status": "new",
			"arrival_date": nowdate(),
			"departure_date": add_days(nowdate(), 1),
			"customer": {"name": "John", "surname": "Doe", "email": "john@example.com"},
			"rooms": [{"room_type_id": "channex-deluxe-uuid", "occupancy": {"adults": 1}}],
			"total_price": 2500.0
		}

		with mock.patch("hospitality_core.api.ota.acknowledge_booking_revision", return_value=True):
			res1 = ota.handle_booking_revision_record(payload)
			res2 = ota.handle_booking_revision_record(payload)

		self.assertEqual(res1["log"], res2["log"])
		count = frappe.db.count("OTA Booking Log", {"ota_booking_id": booking_id})
		self.assertEqual(count, 1)

	def test_ota_booking_cancellation(self):
		"""Cancellation from OTA cancels the corresponding Hotel Reservation."""
		booking_id = "AGODA-" + frappe.generate_hash(length=8)
		new_payload = {
			"id": "rev-301",
			"ota_reservation_code": booking_id,
			"ota_name": "Agoda",
			"status": "new",
			"arrival_date": add_days(nowdate(), 5),
			"departure_date": add_days(nowdate(), 7),
			"customer": {"name": "Anita", "surname": "Patel", "email": "anita@example.com"},
			"rooms": [{"room_type_id": "channex-deluxe-uuid", "occupancy": {"adults": 2}}],
			"total_price": 6000.0
		}

		with mock.patch("hospitality_core.api.ota.acknowledge_booking_revision", return_value=True):
			res_new = ota.handle_booking_revision_record(new_payload)

		res_name = res_new["reservation"]
		self.assertEqual(frappe.db.get_value("Hotel Reservation", res_name, "status"), ReservationStatus.RESERVED)

		# Now send cancel update
		cancel_payload = dict(new_payload)
		cancel_payload["status"] = "cancelled"
		cancel_payload["id"] = "rev-302"

		with mock.patch("hospitality_core.api.ota.acknowledge_booking_revision", return_value=True):
			res_cancel = ota.handle_booking_revision_record(cancel_payload)

		self.assertEqual(res_cancel["status"], "cancelled")
		self.assertEqual(frappe.db.get_value("Hotel Reservation", res_name, "status"), ReservationStatus.CANCELLED)

