"""Reservation -> check-in workflow: room-type inventory, unassigned bookings, identity + room allocation at check-in.
Runs inside the rolled-back test transaction (fixtures from TestHotelFlow)."""
from unittest import mock

import frappe
from frappe.utils import add_days, getdate

from hospitality_core.api import console, website
from hospitality_core.constants import ReservationStatus, RoomStatus
from hospitality_core.hospitality_core.doctype.hotel_reservation import hotel_reservation as hr
from hospitality_core.tests import test_flow


class TestReservationWorkflow(test_flow.TestHotelFlow):
    def test_complete_hotel_lifecycle(self):
        self.skipTest("covered by TestHotelFlow")

    def test_pos_scenarios_a_to_g(self):
        self.skipTest("covered by TestHotelFlow")

    def setUp(self):
        frappe.set_user("Administrator")
        fresh = lambda: frappe.get_doc("Hotel Settings")
        for target in ("hospitality_core.utils.get_settings", "hospitality_core.api.console.get_settings",
                       "hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation.get_settings"):
            p = mock.patch(target, side_effect=fresh)
            p.start()
            self.addCleanup(p.stop)
        for name in frappe.get_all("Hotel Reservation", filters={"status": ["in", ["Reserved", "Checked In"]]}, pluck="name"):
            frappe.db.set_value("Hotel Reservation", name, "status", "Cancelled")
        # only the three fixture rooms belong to the test room type
        for name in frappe.get_all("Hotel Room", filters={"room_type": self.room_type, "name": ["not in", self.rooms]}, pluck="name"):
            frappe.db.set_value("Hotel Room", name, "is_enabled", 0)
        for r in self.rooms:
            frappe.db.set_value("Hotel Room", r, {"status": RoomStatus.AVAILABLE, "current_reservation": None, "is_enabled": 1})
        frappe.db.set_single_value("Hotel Settings", "require_guest_id_at_checkin", 1)
        frappe.db.set_single_value("Hotel Settings", "allow_checkin_before_arrival", 1)
        frappe.db.set_single_value("Hotel Settings", "sales_taxes_template", None)
        self.d0 = add_days(getdate(), 40)

    # ------------------------------------------------------------ helpers
    def book(self, ci=None, co=None, adults=1, **kw):
        data = {"customer": self.customer_name, "room_type": self.room_type,
                "check_in_date": str(ci or self.d0), "check_out_date": str(co or add_days(self.d0, 3)), "adults": adults}
        data.update(kw)
        return frappe.get_doc("Hotel Reservation", console.create_reservation(data)["reservation"]["name"])

    def avail(self, ci, co):
        return hr.get_room_type_availability(self.room_type, ci, co)["available"]

    def legacy(self, room, ci, co):
        """Pre-change style reservation with a physical room already assigned."""
        return frappe.get_doc({"doctype": "Hotel Reservation", "customer": self.customer_name, "room_type": self.room_type,
                               "room": room, "check_in_date": ci, "check_out_date": co, "adults": 1}).insert()

    def other_type_room(self):
        if not frappe.db.exists("Hotel Room Type", "WF Other Type"):
            frappe.get_doc({"doctype": "Hotel Room Type", "room_type_name": "WF Other Type", "default_rate": 100,
                            "item": self.item_code}).insert()
        if not frappe.db.exists("Hotel Room", "WF-901"):
            frappe.get_doc({"doctype": "Hotel Room", "room_number": "WF-901", "room_type": "WF Other Type",
                            "status": "Available", "is_enabled": 1}).insert()
        return "WF-901"

    def today_booking(self):
        return self.book(ci=getdate(), co=add_days(getdate(), 2))

    # ------------------------------------------------------------ availability
    def test_date_ranges_after_full_booking(self):
        d = self.d0
        for _ in self.rooms:
            self.book(d, add_days(d, 3))  # all rooms booked for nights d, d+1, d+2
        self.assertEqual(self.avail(d, add_days(d, 1)), 0)
        self.assertEqual(self.avail(add_days(d, 1), add_days(d, 2)), 0)
        self.assertEqual(self.avail(add_days(d, 2), add_days(d, 3)), 0)
        self.assertEqual(self.avail(add_days(d, 3), add_days(d, 4)), 3)  # checkout day is free (exclusive)
        self.assertEqual(self.avail(add_days(d, 4), add_days(d, 5)), 3)
        self.assertEqual(self.avail(add_days(d, -2), d), 3)               # adjacent before
        self.assertEqual(self.avail(add_days(d, -1), add_days(d, 1)), 0)  # partial overlap

    def test_insufficient_inventory_and_cancel_releases(self):
        made = [self.book() for _ in self.rooms]
        with self.assertRaises(hr.RoomTypeUnavailable):
            self.book()
        self.assertEqual(self.avail(self.d0, add_days(self.d0, 3)), 0)  # never negative
        console.cancel_reservation(made[0].name)
        self.assertEqual(self.avail(self.d0, add_days(self.d0, 3)), 1)
        self.book()
        self.assertEqual(self.avail(self.d0, add_days(self.d0, 3)), 0)

    def test_non_overlapping_bookings_do_not_stack(self):
        # 3 rooms booked on night 1 and 3 others on night 2 only: range over both nights has peak 3, not 6
        for _ in self.rooms:
            self.book(self.d0, add_days(self.d0, 1))
        for _ in self.rooms:
            self.book(add_days(self.d0, 1), add_days(self.d0, 2))
        self.assertEqual(self.avail(self.d0, add_days(self.d0, 2)), 0)
        self.assertEqual(self.avail(add_days(self.d0, 2), add_days(self.d0, 3)), 3)

    def test_legacy_assigned_and_unassigned_count_once(self):
        self.legacy(self.rooms[0], self.d0, add_days(self.d0, 2))
        self.book(self.d0, add_days(self.d0, 2))
        self.assertEqual(self.avail(self.d0, add_days(self.d0, 2)), 1)
        # legacy room is still physically blocked for other assignments
        self.assertNotIn(self.rooms[0], [r.name for r in hr.get_available_rooms(self.room_type, self.d0, add_days(self.d0, 1))])

    def test_past_and_checked_out_do_not_block(self):
        res = self.today_booking()
        console.check_in(res.name, room=self.rooms[0], guest_id_type="Passport", guest_id_number="Z1234567")
        self.assertEqual(self.avail(getdate(), add_days(getdate(), 1)), 2)  # in-house guest blocks
        self.assertEqual(self.avail(self.d0, add_days(self.d0, 1)), 3)      # but not unrelated future dates

    def test_out_of_order_room_reduces_inventory(self):
        frappe.db.set_value("Hotel Room", self.rooms[2], "status", RoomStatus.OUT_OF_ORDER)
        self.assertEqual(self.avail(self.d0, add_days(self.d0, 1)), 2)
        self.book(); self.book()
        with self.assertRaises(hr.RoomTypeUnavailable):
            self.book()

    def test_capacity_validation(self):
        frappe.db.set_value("Hotel Room Type", self.room_type, {"max_adults": 2, "max_children": 1, "max_occupancy": 3})
        with self.assertRaises(frappe.ValidationError):
            self.book(adults=3)
        self.book(adults=2, children=1)

    # ------------------------------------------------------------ reservation creation
    def test_reservation_has_no_physical_room_and_correct_price(self):
        res = self.book(remarks="late arrival")
        self.assertEqual(res.status, ReservationStatus.RESERVED)
        self.assertFalse(res.room)
        self.assertFalse(res.stays[0].room)
        self.assertEqual(res.stays[0].rate, hr.get_room_rate(self.room_type, res.check_in_date, res.customer))
        self.assertFalse(res.get("guest_id_number"))
        # a client-supplied room or ID is ignored at booking
        res2 = self.book(room=self.rooms[0], guest_id_type="PAN", guest_id_number="ABCDE1234F")
        self.assertFalse(res2.room)
        self.assertFalse(res2.get("guest_id_number"))

    def test_new_guest_created_without_identity(self):
        out = console.create_reservation({"guest_name": "Wf New Guest", "mobile_no": "+919999900000", "room_type": self.room_type,
                                          "check_in_date": str(self.d0), "check_out_date": str(add_days(self.d0, 1)), "adults": 1})
        cust = frappe.get_doc("Customer", out["reservation"]["customer"])
        self.assertFalse(cust.get("guest_id_number"))

    def test_website_booking_unassigned_and_shared_inventory(self):
        frappe.db.set_single_value("Hotel Settings", {"is_active": 1, "is_published": 1, "min_billable_nights": 1})
        frappe.db.set_value("Hotel Room Type", self.room_type, {"is_active": 1, "is_published": 1, "max_adults": 2, "max_children": 1, "max_occupancy": 3})
        ci, co = str(self.d0), str(add_days(self.d0, 2))
        r = website._create_booking(self.room_type, ci, co, 2, 0, 1, None, "Wf Web Guest", "wf.web@example.com", "+91 99999 11111", None)
        res = frappe.get_doc("Hotel Reservation", r["booking_references"][0])
        self.assertFalse(res.room)
        self.assertEqual(res.status, ReservationStatus.RESERVED)
        self.assertEqual(website._free_inventory(self.room_type, ci, co), 2)
        self.book(self.d0, add_days(self.d0, 2)); self.book(self.d0, add_days(self.d0, 2))
        with self.assertRaises(website.BookingUnavailable):
            website._create_booking(self.room_type, ci, co, 1, 0, 1, None, "Wf Web Two", "wf.two@example.com", "+91 99999 22222", None)
        # an adjacent stay is still bookable online
        nxt = website._create_booking(self.room_type, co, str(add_days(self.d0, 3)), 1, 0, 1, None, "Wf Web Three",
                                      "wf.three@example.com", "+91 99999 33333", None)
        self.assertTrue(nxt["booking_references"])

    # ------------------------------------------------------------ check-in
    def test_checkin_requires_identity(self):
        res = self.today_booking()
        with self.assertRaises(hr.IdentityRequired):
            console.check_in(res.name, room=self.rooms[0])
        with self.assertRaises(frappe.ValidationError):
            console.check_in(res.name, room=self.rooms[0], guest_id_type="Aadhaar", guest_id_number="1234")
        self.assertEqual(frappe.db.get_value("Hotel Reservation", res.name, "status"), ReservationStatus.RESERVED)

    def test_checkin_requires_room(self):
        res = self.today_booking()
        with self.assertRaises(frappe.ValidationError):
            console.check_in(res.name, guest_id_type="Passport", guest_id_number="Z1234567")

    def test_successful_checkin_assigns_room(self):
        res = self.today_booking()
        rooms = console.get_checkin_details(res.name)["rooms"]
        self.assertEqual({r["name"] for r in rooms}, set(self.rooms))
        out = console.check_in(res.name, room=self.rooms[1], guest_id_type="Aadhaar", guest_id_number="1234 5678 9012")
        doc = frappe.get_doc("Hotel Reservation", res.name)
        self.assertEqual(doc.status, ReservationStatus.CHECKED_IN)
        self.assertEqual(doc.room, self.rooms[1])
        self.assertEqual(doc.stays[0].room, self.rooms[1])
        self.assertTrue(doc.checked_in_on)
        self.assertEqual(doc.id_verified_by, "Administrator")
        self.assertEqual(doc.guest_id_number, "123456789012")
        self.assertEqual(out["reservation"]["guest_id_number"], "XXXXXXXX9012")  # masked in API output
        self.assertEqual(frappe.db.get_value("Hotel Room", self.rooms[1], "status"), RoomStatus.OCCUPIED)
        details = console.get_reservation_details(res.name)
        self.assertNotIn("123456789012", frappe.as_json(details))
        versions = frappe.get_all("Version", filters={"ref_doctype": "Hotel Reservation", "docname": res.name}, pluck="data")
        self.assertFalse(any("123456789012" in (v or "") for v in versions))
        data = console.get_console_data()
        self.assertIn(res.name, [r.name for r in data["in_house"]])

    def test_checkin_rejects_wrong_type_occupied_ooo_dirty(self):
        first, second = self.today_booking(), self.today_booking()
        ident = {"guest_id_type": "Passport", "guest_id_number": "Z1234567"}
        with self.assertRaises(hr.RoomUnavailable):
            console.check_in(first.name, room=self.other_type_room(), **ident)
        frappe.db.set_value("Hotel Room", self.rooms[2], "status", RoomStatus.OUT_OF_ORDER)
        with self.assertRaises(hr.RoomUnavailable):
            console.check_in(first.name, room=self.rooms[2], **ident)
        frappe.db.set_value("Hotel Room", self.rooms[1], "status", RoomStatus.DIRTY)
        with self.assertRaises(hr.RoomUnavailable):
            console.check_in(first.name, room=self.rooms[1], **ident)
        console.check_in(first.name, room=self.rooms[0], **ident)
        # second receptionist allocating the same room is rejected; reservation stays Reserved
        with self.assertRaises(hr.RoomUnavailable):
            console.check_in(second.name, room=self.rooms[0], **ident)
        self.assertEqual(frappe.db.get_value("Hotel Reservation", second.name, "status"), ReservationStatus.RESERVED)
        self.assertNotIn(self.rooms[0], [r["name"] for r in console.get_checkin_details(second.name)["rooms"]])

    def test_checkin_rejects_room_assigned_to_overlapping_legacy(self):
        self.legacy(self.rooms[0], getdate(), add_days(getdate(), 2))
        res = self.today_booking()
        with self.assertRaises(hr.RoomUnavailable):
            console.check_in(res.name, room=self.rooms[0], guest_id_type="Passport", guest_id_number="Z1234567")

    def test_id_document_must_be_private_and_allowed_type(self):
        res = self.today_booking()
        with self.assertRaises(frappe.ValidationError):
            console.check_in(res.name, room=self.rooms[0], guest_id_type="Passport", guest_id_number="Z1234567",
                             guest_id_document="/files/id.png")
        with self.assertRaises(frappe.ValidationError):
            console.check_in(res.name, room=self.rooms[0], guest_id_type="Passport", guest_id_number="Z1234567",
                             guest_id_document="/private/files/id.exe")
        f = frappe.get_doc({"doctype": "File", "file_name": "wf_id.png", "is_private": 1,
                            "content": b"\x89PNG\r\n\x1a\n" + b"0" * 16}).insert()
        console.check_in(res.name, room=self.rooms[0], guest_id_type="Passport", guest_id_number="Z1234567",
                         guest_id_document=f.file_url)
        self.assertEqual(frappe.db.get_value("File", f.name, "attached_to_name"), res.name)

    # ------------------------------------------------------------ console / regression
    def test_console_shows_unassigned_arrival_without_marking_rooms(self):
        res = self.today_booking()
        data = console.get_console_data()
        self.assertIn(res.name, [a.name for a in data["arrivals"]])
        self.assertTrue(all(r.status == RoomStatus.AVAILABLE for r in data["rooms"] if r.name in self.rooms))
        self.assertIn(res.name, [r.name for r in console.get_reservations(status="Reserved")])
        self.assertNotIn(res.name, [r.name for r in data["in_house"]])

    def test_walk_in_assigns_room_with_identity(self):
        out = console.walk_in({"customer": self.customer_name, "room_type": self.room_type, "room": self.rooms[2],
                               "check_out_date": str(add_days(getdate(), 1)), "adults": 1,
                               "guest_id_type": "Passport", "guest_id_number": "Z7654321"})
        self.assertEqual(out["reservation"]["room"], self.rooms[2])
        self.assertEqual(out["reservation"]["status"], ReservationStatus.CHECKED_IN)

    def test_checkout_after_checkin(self):
        frappe.db.set_single_value("Hotel Settings", "block_checkout_if_balance", 0)
        res = self.today_booking()
        console.check_in(res.name, room=self.rooms[0], guest_id_type="Passport", guest_id_number="Z1234567")
        out = hr.check_out(res.name)
        self.assertTrue(out["sales_invoice"])
        self.assertEqual(frappe.db.get_value("Hotel Room", self.rooms[0], "status"), RoomStatus.DIRTY)
        self.assertEqual(self.avail(getdate(), add_days(getdate(), 1)), 3)
