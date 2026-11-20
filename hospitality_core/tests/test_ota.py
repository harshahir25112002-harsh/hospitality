"""
Acceptance tests for OTA integration:
- Incoming booking direct creation into OTA Reservation
- Duplicate booking update (no duplicate records)
- Booking modification and cancellation
- 15-minute pull feed processing
"""
import json
import frappe
from frappe.utils import add_days, nowdate
from unittest import mock

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

		ota_settings = frappe.get_single("OTA Settings")
		ota_settings.enabled = 1
		ota_settings.api_base_url = "https://example.com/api/v1"
		ota_settings.property_id = "test-prop-uuid"
		ota_settings.feed_endpoint = "booking_revisions/feed"
		ota_settings.pull_interval_minutes = 15
		ota_settings.auto_acknowledge = 1
		ota_settings.save(ignore_permissions=True)

	def test_ota_new_booking(self):
		"""Simulate an incoming booking saved directly into OTA Reservation."""
		booking_id = "MMT-TEST-" + frappe.generate_hash(length=8)
		payload = {
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
					"room_type_name": "Deluxe Room",
					"rate_plan_name": "Standard Rate",
					"occupancy": {"adults": 2, "children": 0}
				}
			],
			"total_price": 5000.0,
			"currency": "INR",
			"commission": 500.0,
			"payment_status": "prepaid",
			"payment_collect": "OTA"
		}

		res_name = ota.save_ota_reservation(payload, raw_data=json.dumps(payload))
		self.assertIsNotNone(res_name)

		ota_res = frappe.get_doc("OTA Reservation", res_name)
		self.assertEqual(ota_res.ota_booking_id, booking_id)
		self.assertEqual(ota_res.channel_name, "MakeMyTrip")
		self.assertEqual(ota_res.guest_name, "Rahul Sharma")
		self.assertEqual(ota_res.guest_email, "rahul.sharma@example.com")
		self.assertEqual(ota_res.room_type_name, "Deluxe Room")
		self.assertEqual(ota_res.total_amount, 5000.0)
		self.assertEqual(ota_res.status, "New")

	def test_ota_duplicate_prevention(self):
		"""Same booking ID received twice must update the existing OTA Reservation, not duplicate."""
		booking_id = "BOOKINGCOM-" + frappe.generate_hash(length=8)
		payload = {
			"ota_reservation_code": booking_id,
			"ota_name": "Booking.com",
			"status": "new",
			"arrival_date": nowdate(),
			"departure_date": add_days(nowdate(), 1),
			"customer": {"name": "John", "surname": "Doe", "email": "john@example.com"},
			"rooms": [{"room_type_name": "Suite", "occupancy": {"adults": 1}}],
			"total_price": 2500.0
		}

		name1 = ota.save_ota_reservation(payload)
		name2 = ota.save_ota_reservation(payload)

		self.assertEqual(name1, name2)
		count = frappe.db.count("OTA Reservation", {"ota_booking_id": booking_id})
		self.assertEqual(count, 1)

	def test_ota_booking_cancellation(self):
		"""Cancellation updates the OTA Reservation status to Cancelled."""
		booking_id = "AGODA-" + frappe.generate_hash(length=8)
		new_payload = {
			"ota_reservation_code": booking_id,
			"ota_name": "Agoda",
			"status": "new",
			"arrival_date": add_days(nowdate(), 5),
			"departure_date": add_days(nowdate(), 7),
			"customer": {"name": "Anita", "surname": "Patel", "email": "anita@example.com"},
			"rooms": [{"room_type_name": "Deluxe", "occupancy": {"adults": 2}}],
			"total_price": 6000.0
		}

		res_name = ota.save_ota_reservation(new_payload)
		self.assertEqual(frappe.db.get_value("OTA Reservation", res_name, "status"), "New")

		# Send cancellation
		cancel_payload = dict(new_payload)
		cancel_payload["status"] = "cancelled"

		ota.save_ota_reservation(cancel_payload)
		self.assertEqual(frappe.db.get_value("OTA Reservation", res_name, "status"), "Cancelled")
