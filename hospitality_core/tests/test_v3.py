"""
v3 regression tests: accounting safety, validations, permissions and console API.
Runs inside a rolled-back test transaction (IntegrationTestCase class cleanup).
"""
import frappe
from frappe.utils import add_days, flt, getdate, nowdate

from hospitality_core.api import console
from hospitality_core.constants import ReservationStatus, RoomStatus
from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import check_in, check_out
from hospitality_core.pos import charge_to_room
from hospitality_core.tests import test_flow


class TestHotelV3(test_flow.TestHotelFlow):
    # reuse fixtures from TestHotelFlow.setUpClass, but not its tests
    def test_complete_hotel_lifecycle(self):
        self.skipTest("covered by TestHotelFlow")

    def test_pos_scenarios_a_to_g(self):
        self.skipTest("covered by TestHotelFlow")

    def setUp(self):
        frappe.set_user("Administrator")
        # The live bench shares Redis with tests and re-caches committed (pre-test) Hotel Settings,
        # so read settings from the in-transaction DB in every module that uses them.
        from unittest import mock
        fresh = lambda: frappe.get_doc("Hotel Settings")
        for target in ("hospitality_core.utils.get_settings", "hospitality_core.pos.get_settings",
                       "hospitality_core.api.console.get_settings",
                       "hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation.get_settings"):
            p = mock.patch(target, side_effect=fresh)
            p.start()
            self.addCleanup(p.stop)
        # isolate each test: release all rooms / stays created by previous tests in this class
        for name in frappe.get_all("Hotel Reservation", filters={"status": ["in", ["Reserved", "Checked In"]]}, pluck="name"):
            frappe.db.set_value("Hotel Reservation", name, "status", "Cancelled")
        for r in self.rooms:
            frappe.db.set_value("Hotel Room", r, {"status": RoomStatus.AVAILABLE, "current_reservation": None})
        frappe.db.set_single_value("Hotel Settings", "sales_taxes_template", None)
        frappe.clear_document_cache("Hotel Settings", "Hotel Settings")

    # ---------- helpers ----------
    def make_res(self, room, start, end, customer=None, checkin=False):
        res = frappe.get_doc({
            "doctype": "Hotel Reservation", "company": self.company, "customer": customer or self.customer_name,
            "room_type": self.room_type, "room": room, "check_in_date": start, "check_out_date": end, "adults": 1,
        }).insert(ignore_permissions=True)
        if checkin:
            check_in(res.name)
            res.reload()
        return res

    def pay(self, res_name, amount):
        return console.receive_payment(res_name, "Cash", amount, "T-REF")["payment_entry"]

    def room_order(self, res, rate, paid):
        inv = frappe.new_doc("Sales Invoice")
        inv.company = self.company
        inv.customer = res.customer
        inv.pos_profile = self.pos_profiles["room"]
        inv.hotel_reservation = res.name
        inv.append("items", {"item_code": self.food_item, "qty": 1, "rate": rate})
        if paid:
            inv.is_pos = 1
            inv.append("payments", {"mode_of_payment": "Cash", "account": self.paid_to, "amount": rate, "default": 1})
            inv.insert(ignore_permissions=True)
            inv.submit()
        else:
            inv.insert(ignore_permissions=True)
            charge_to_room(inv.name, res.name)
        return inv.name

    def other_customer(self, name="V3 Other Guest"):
        if not frappe.db.exists("Customer", name):
            frappe.get_doc({"doctype": "Customer", "customer_name": name, "customer_type": "Individual", "is_hotel_guest": 1}).insert(ignore_permissions=True)
        return name

    # ---------- tests ----------
    def test_advance_only_from_same_reservation(self):
        today = getdate(nowdate())
        future = self.make_res(self.rooms[2], add_days(today, 30), add_days(today, 32))
        future_pe = self.pay(future.name, 1000)
        stay = self.make_res(self.rooms[0], today, add_days(today, 1), checkin=True)
        stay_pe = self.pay(stay.name, 300)

        out = check_out(stay.name)
        inv = frappe.get_doc("Sales Invoice", out["sales_invoice"])
        refs = {a.reference_name for a in inv.advances}
        self.assertIn(stay_pe, refs)
        self.assertNotIn(future_pe, refs, "another reservation's deposit must not be consumed")
        self.assertEqual(flt(frappe.db.get_value("Payment Entry", future_pe, "unallocated_amount")), 1000)
        self.assertEqual(flt(inv.outstanding_amount), 0)

    def test_duplicate_checkout_blocked(self):
        today = getdate(nowdate())
        stay = self.make_res(self.rooms[0], today, add_days(today, 1), checkin=True)
        self.pay(stay.name, 500)
        check_out(stay.name)
        self.assertRaises(frappe.ValidationError, check_out, stay.name)
        invoices = frappe.get_all("Sales Invoice", filters={"hotel_reservation": stay.name, "hotel_order_type": "Stay Checkout", "docstatus": 1})
        self.assertEqual(len(invoices), 1)
        self.assertEqual(frappe.db.get_value("Hotel Room", self.rooms[0], "status"), RoomStatus.DIRTY)

    def test_extend_stay_conflict(self):
        today = getdate(nowdate())
        a = self.make_res(self.rooms[1], add_days(today, 20), add_days(today, 22))
        self.make_res(self.rooms[1], add_days(today, 22), add_days(today, 24), customer=self.other_customer())
        self.assertRaises(frappe.ValidationError, console.extend_stay, a.name, add_days(today, 23))
        # extending into free nights works
        console.extend_stay(a.name, add_days(today, 22))
        b = self.make_res(self.rooms[2], add_days(today, 40), add_days(today, 41))
        out = console.extend_stay(b.name, add_days(today, 44))
        self.assertEqual(getdate(out["reservation"]["check_out_date"]), getdate(add_days(today, 44)))

    def test_double_booking_and_move_blocked(self):
        today = getdate(nowdate())
        stay = self.make_res(self.rooms[0], today, add_days(today, 2), checkin=True)
        self.assertRaises(frappe.ValidationError, self.make_res, self.rooms[0], today, add_days(today, 1), self.other_customer())
        other = self.make_res(self.rooms[1], today, add_days(today, 2), customer=self.other_customer(), checkin=True)
        self.assertRaises(frappe.ValidationError, console.move_room, stay.name, other.room)
        self.assertRaises(frappe.ValidationError, console.move_room, stay.name, stay.room)

    def test_payment_validation(self):
        today = getdate(nowdate())
        res = self.make_res(self.rooms[0], add_days(today, 5), add_days(today, 6))
        self.assertRaises(frappe.ValidationError, console.receive_payment, res.name, "Cash", 0)
        self.assertRaises(frappe.ValidationError, console.receive_payment, res.name, "Cash", -5)
        pe = self.pay(res.name, 200)
        pe_doc = frappe.get_doc("Payment Entry", pe)
        self.assertEqual(pe_doc.party, res.customer)
        self.assertEqual(pe_doc.hotel_reservation, res.name)
        self.assertEqual(pe_doc.payment_type, "Receive")
        self.pay(res.name, 100)  # multiple payments
        details = console.get_reservation_details(res.name)
        self.assertEqual(len(details["payments"]), 2)
        self.assertEqual(flt(details["billing"]["total_paid"]), 300)
        console.cancel_reservation(res.name)
        self.assertRaises(frappe.ValidationError, console.receive_payment, res.name, "Cash", 50)

    def test_room_service_revenue_once(self):
        today = getdate(nowdate())
        stay = self.make_res(self.rooms[0], today, add_days(today, 1), checkin=True)
        paid = self.room_order(stay, 60, paid=True)
        unpaid1 = self.room_order(stay, 100, paid=False)
        unpaid2 = self.room_order(stay, 40, paid=False)

        preview = console.get_bill_preview(stay.name)
        sources = [i["source"] for i in preview["items"]]
        self.assertNotIn(paid, sources, "paid POS order must not be billed again")
        self.assertIn(unpaid1, sources)
        self.assertIn(unpaid2, sources)

        self.pay(stay.name, preview["grand_total"])
        inv_name = check_out(stay.name)["sales_invoice"]
        inv = frappe.get_doc("Sales Invoice", inv_name)
        room_total = sum(flt(i.amount) for i in inv.items if not i.hotel_source_invoice)
        rs_total = sum(flt(i.amount) for i in inv.items if i.hotel_source_invoice)
        self.assertEqual(rs_total, 140)
        self.assertFalse(frappe.db.exists("Sales Invoice", unpaid1))

        # GL: income credited exactly once per sale
        income = frappe.db.sql("""
            SELECT SUM(gle.credit - gle.debit) FROM `tabGL Entry` gle
            JOIN `tabAccount` a ON a.name = gle.account
            WHERE gle.voucher_type = 'Sales Invoice' AND gle.voucher_no IN %s
              AND a.root_type = 'Income' AND gle.is_cancelled = 0
        """, ((inv_name, paid),))[0][0]
        self.assertEqual(flt(income, 2), flt(room_total + 140 + 60, 2))

    def test_charge_to_room_wrong_guest_blocked(self):
        today = getdate(nowdate())
        stay = self.make_res(self.rooms[0], today, add_days(today, 1), checkin=True)
        other = self.other_customer()
        self.make_res(self.rooms[1], today, add_days(today, 1), customer=other, checkin=True)
        inv = frappe.new_doc("Sales Invoice")
        inv.company = self.company
        inv.customer = other
        inv.pos_profile = self.pos_profiles["room"]
        inv.append("items", {"item_code": self.food_item, "qty": 1, "rate": 10})
        inv.insert(ignore_permissions=True)
        self.assertRaises(frappe.ValidationError, charge_to_room, inv.name, stay.name)

    def test_tax_on_checkout_invoice(self):
        tax_account = frappe.db.get_value("Account", {"company": self.company, "account_type": "Tax", "is_group": 0})
        if not tax_account:
            self.skipTest("no Tax account in company")
        tname = "V3 Hotel Tax"
        if not frappe.db.exists("Sales Taxes and Charges Template", f"{tname} - {frappe.db.get_value('Company', self.company, 'abbr')}"):
            frappe.get_doc({
                "doctype": "Sales Taxes and Charges Template", "title": tname, "company": self.company,
                "taxes": [{"charge_type": "On Net Total", "account_head": tax_account, "rate": 10, "description": "Hotel Tax"}],
            }).insert(ignore_permissions=True)
        template = frappe.db.get_value("Sales Taxes and Charges Template", {"title": tname, "company": self.company})
        frappe.db.set_single_value("Hotel Settings", "sales_taxes_template", template)
        frappe.clear_document_cache("Hotel Settings", "Hotel Settings")

        today = getdate(nowdate())
        stay = self.make_res(self.rooms[0], today, add_days(today, 1), checkin=True)
        preview = console.get_bill_preview(stay.name)
        self.pay(stay.name, preview["grand_total"])
        inv = frappe.get_doc("Sales Invoice", check_out(stay.name)["sales_invoice"])
        self.assertEqual(flt(inv.total_taxes_and_charges, 2), flt(inv.net_total * 0.10, 2))
        self.assertEqual(flt(inv.outstanding_amount), 0)

    def test_console_api(self):
        today = getdate(nowdate())
        stay = self.make_res(self.rooms[0], today, add_days(today, 2), checkin=True)
        # future booking of the same room must not hide the in-house guest on the board
        self.make_res(self.rooms[0], add_days(today, 10), add_days(today, 11), customer=self.other_customer())
        arrival = self.make_res(self.rooms[1], today, add_days(today, 1), customer=self.other_customer())

        data = console.get_console_data(today)
        board = {r.name: r for r in data["rooms"]}
        self.assertEqual(board[self.rooms[0]]["reservation"], stay.name)
        self.assertIn(arrival.name, [a.name for a in data["arrivals"]])
        self.assertIn("setup_warnings", data)
        self.assertGreaterEqual(data["kpis"]["occupied"], 1)

        console.change_reserved_room(arrival.name, self.rooms[2])
        self.assertEqual(frappe.db.get_value("Hotel Room", self.rooms[2], "status"), RoomStatus.RESERVED)
        self.assertEqual(frappe.db.get_value("Hotel Room", self.rooms[1], "status"), RoomStatus.AVAILABLE)
        self.assertRaises(frappe.ValidationError, console.change_reserved_room, stay.name, self.rooms[1])

        rows = console.get_reservations(status="Checked In")
        self.assertIn(stay.name, [r.name for r in rows])
        self.assertTrue(console.search(stay.name[:6]))

    def test_walk_in_and_create_with_advance(self):
        today = getdate(nowdate())
        out = console.create_reservation(
            {"guest_name": "V3 New Guest", "room_type": self.room_type, "room": self.rooms[2],
             "check_in_date": add_days(today, 3), "check_out_date": add_days(today, 5), "bogus_field": "x"},
            {"amount": 250, "mode": "Cash"},
        )
        self.assertTrue(out["payment_entry"])
        self.assertTrue(frappe.db.get_value("Customer", out["reservation"]["customer"], "is_hotel_guest"))
        wi = console.walk_in({"customer": self.customer_name, "room_type": self.room_type, "room": self.rooms[0],
                              "check_out_date": add_days(today, 1)})
        self.assertEqual(wi["reservation"]["status"], ReservationStatus.CHECKED_IN)
        self.assertEqual(frappe.db.get_value("Hotel Room", self.rooms[0], "status"), RoomStatus.OCCUPIED)

    def test_housekeeping_rules(self):
        today = getdate(nowdate())
        self.make_res(self.rooms[0], today, add_days(today, 1), checkin=True)
        self.assertRaises(frappe.ValidationError, console.set_housekeeping, self.rooms[0], "Dirty")
        self.assertRaises(frappe.ValidationError, console.set_housekeeping, self.rooms[0], "Clean")
        console.set_housekeeping(self.rooms[1], "Dirty")
        self.assertEqual(console.set_housekeeping(self.rooms[1], "Clean")["status"], RoomStatus.AVAILABLE)

    def test_maintenance_issue(self):
        out = console.report_issue(self.rooms[2], "V3 leaking tap", "High")
        self.assertEqual(frappe.db.get_value("Hotel Room", self.rooms[2], "status"), RoomStatus.OUT_OF_ORDER)
        console.resolve_issue(out["issue"], "fixed")
        self.assertNotEqual(frappe.db.get_value("Hotel Room", self.rooms[2], "status"), RoomStatus.OUT_OF_ORDER)

    def test_permissions(self):
        frappe.set_user("Guest")
        try:
            self.assertRaises(frappe.PermissionError, console.get_console_data)
            self.assertRaises(frappe.PermissionError, console.receive_payment, "X", "Cash", 1)
        finally:
            frappe.set_user("Administrator")
