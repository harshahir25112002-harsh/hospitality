"""
Public website API: dynamic content, availability, server pricing and genuine reservations.
Runs inside a rolled-back test transaction with far-future dates and `_WT` test records.
"""
import io
import json
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate

from hospitality_core.api import website

PREFIX = "_WT "


def png(seed):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (seed * 37 % 256, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


class TestHotelWebsite(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.files = [frappe.get_doc({"doctype": "File", "file_name": f"wt_img_{i}.png", "content": png(i + 10),
                                     "is_private": 0}).insert(ignore_permissions=True).file_url for i in range(3)]
        cls.amenity = frappe.get_doc({"doctype": "Hotel Amenity", "amenity_name": f"{PREFIX}Sea Breeze",
                                      "amenity_code": "WT_BREEZE", "icon_name": "wind", "applies_to": "Room and Property"}).insert().name
        cls.amenity2 = frappe.get_doc({"doctype": "Hotel Amenity", "amenity_name": f"{PREFIX}Minibar",
                                       "amenity_code": "WT_MINIBAR", "icon_name": "refrigerator"}).insert().name
        s = frappe.get_doc("Hotel Settings")
        cls.original_template = s.sales_taxes_template
        s.update({"hotel_name": "WT Test Hotel", "property_short_description": "Test property", "address_line": "1 Test Road",
                  "city": "Pune", "country": frappe.db.get_value("Country", {}, "name"), "contact_number": "+91 1234567890",
                  "email_address": "wt@example.com", "is_active": 1, "is_published": 1, "sales_taxes_template": None,
                  "min_billable_nights": 1})
        s.set("property_images", [{"image": cls.files[0], "image_caption": "Front"}])
        s.save()
        cls.rt = cls.make_room_type("Ocean", default_rate=5000)
        cls.rooms = []
        for n in ("WT-1", "WT-2"):
            frappe.get_doc({"doctype": "Hotel Room", "room_number": n, "room_type": cls.rt, "status": "Available",
                            "is_enabled": 1}).insert()
            cls.rooms.append(n)
        cls.ci = add_days(getdate(), 200)
        cls.co = add_days(cls.ci, 3)

    @classmethod
    def tearDownClass(cls):
        frappe.set_user("Administrator")
        for f in cls.files:
            frappe.delete_doc("File", frappe.db.get_value("File", {"file_url": f}), force=True, ignore_permissions=True)
        super().tearDownClass()

    @classmethod
    def make_room_type(cls, name, published=1, **kw):
        doc = {"doctype": "Hotel Room Type", "room_type_name": f"{PREFIX}{name}", "max_adults": 2, "max_children": 1,
               "max_occupancy": 3, "description": f"{name} room", "bed_configuration": "King Bed", "is_published": published,
               "images": [{"image": cls.files[1], "image_caption": "Bed"}], "amenities": [{"amenity": cls.amenity}]}
        doc.update(kw)
        return frappe.get_doc(doc).insert().name

    def setUp(self):
        frappe.db.savepoint("wt_case")  # each test starts from the class fixtures
        frappe.set_user("Guest")
        self.token_n = 0

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback(save_point="wt_case")

    def token(self):
        self.token_n += 1
        return f"wt-test-token-{self._testMethodName[-20:]}-{self.token_n}".replace("_", "-")

    def book(self, **kw):
        args = dict(room_type=self.rt, check_in=str(self.ci), check_out=str(self.co), adults=2, children=0, rooms=1,
                    guest_name="Wt Guest", email="wt.guest@example.com", phone="+91 99999 00000",
                    booking_token=self.token())
        args.update(kw)
        return website.create_booking(**args)

    def search(self, **kw):
        args = dict(check_in=str(self.ci), check_out=str(self.co), adults=2, children=0, rooms=1)
        args.update(kw)
        res = website.search_availability(**args)
        return {r["room_type"]: r for r in res["results"]}

    def admin_reservation(self, room, ci=None, co=None):
        frappe.set_user("Administrator")
        customer = frappe.get_all("Customer", limit=1, pluck="name")[0]
        doc = frappe.get_doc({"doctype": "Hotel Reservation", "customer": customer, "room_type": self.rt, "room": room,
                              "check_in_date": ci or self.ci, "check_out_date": co or self.co, "adults": 1}).insert()
        frappe.set_user("Guest")
        return doc

    # ---------- A/B: dynamic content ----------
    def test_unpublished_hotel_is_hidden(self):
        frappe.db.set_single_value("Hotel Settings", "is_published", 0)
        self.assertRaises(frappe.DoesNotExistError, website.get_site_data)
        self.assertRaises(frappe.DoesNotExistError, self.search)
        frappe.db.set_single_value("Hotel Settings", "is_published", 1)

    def test_site_data_is_dynamic_and_public_safe(self):
        data = website.get_site_data()
        self.assertEqual(data["hotel"]["name"], "WT Test Hotel")
        self.assertEqual(data["hotel"]["images"][0]["url"], self.files[0])
        names = [r["name"] for r in data["room_types"]]
        self.assertIn(self.rt, names)
        rt = next(r for r in data["room_types"] if r["name"] == self.rt)
        self.assertEqual(rt["starting_price"], 5000)
        self.assertEqual(rt["images"][0]["url"], self.files[1])
        # new published room type appears; unpublished does not
        frappe.set_user("Administrator")
        new_rt = self.make_room_type("Garden", default_rate=3000)
        hidden = self.make_room_type("Hidden", published=0, default_rate=1000)
        # update description, image and amenities of an existing room type
        doc = frappe.get_doc("Hotel Room Type", self.rt)
        doc.description = "Updated ocean room"
        doc.images[0].image = self.files[2]
        doc.append("amenities", {"amenity": self.amenity2})
        doc.save()
        frappe.set_user("Guest")
        data = website.get_site_data()
        names = [r["name"] for r in data["room_types"]]
        self.assertIn(new_rt, names)
        self.assertNotIn(hidden, names)
        rt = next(r for r in data["room_types"] if r["name"] == self.rt)
        self.assertEqual(rt["description"], "Updated ocean room")
        self.assertEqual(rt["primary_image"], self.files[2])
        self.assertEqual({a["name"] for a in rt["amenities"]}, {self.amenity, self.amenity2})
        blob = json.dumps(data, default=str)
        for secret in ("WT-1", "customer", "company", "sales_taxes_template", "current_reservation"):
            self.assertNotIn(secret, blob)
        self.assertRaises(frappe.DoesNotExistError, website.get_room_type, hidden)

    # ---------- C: availability ----------
    def test_availability_follows_reservations(self):
        r = self.search()[self.rt]
        self.assertTrue(r["available"])
        self.assertEqual(r["rooms_left"], 2)
        self.assertEqual(r["offers"][0]["rate_plan"], None)  # no plans -> room type default rate
        self.assertEqual(r["offers"][0]["total"], 15000)
        self.admin_reservation("WT-1")
        r = self.search()[self.rt]
        self.assertTrue(r["available"])
        self.assertEqual(r["rooms_left"], 1)
        self.assertFalse(self.search(rooms=2, adults=2)[self.rt]["available"])
        self.admin_reservation("WT-2", ci=add_days(self.ci, 2), co=add_days(self.co, 2))  # partial overlap
        r = self.search()[self.rt]
        self.assertFalse(r["available"])
        # WT-1 is free again from its check-out day; WT-2 still occupies co..co+2
        r = self.search(check_in=str(self.co), check_out=str(add_days(self.co, 1)))[self.rt]
        self.assertTrue(r["available"])
        self.assertEqual(r["rooms_left"], 1)
        self.assertTrue(self.search(check_in=str(add_days(self.co, 2)), check_out=str(add_days(self.co, 3)))[self.rt]["available"])

    def test_out_of_order_room_not_offered(self):
        frappe.db.set_value("Hotel Room", "WT-1", "status", "Out of Order")
        self.assertEqual(self.search()[self.rt]["rooms_left"], 1)
        frappe.db.set_value("Hotel Room", "WT-1", "status", "Available")

    # ---------- D: pricing + booking ----------
    def make_plans(self):
        frappe.set_user("Administrator")
        base = dict(doctype="Room Rate Plan", room_type=self.rt, valid_from=self.ci, valid_to=self.co, active=1)
        std = frappe.get_doc(dict(base, plan_name=f"{PREFIX}Std", rate=4000, meal_plan="Room Only", is_refundable=0)).insert()
        bf = frappe.get_doc(dict(base, plan_name=f"{PREFIX}BF", rate=5000, meal_plan="Breakfast Included", free_cancellation=1,
                                 free_cancellation_hours=24, discount_percentage=10, included_adults=1,
                                 extra_adult_charge=700, included_children=0)).insert()
        frappe.set_user("Guest")
        return std, bf

    def test_quote_is_server_side(self):
        std, bf = self.make_plans()
        offers = {o["rate_plan"]: o for o in self.search()[self.rt]["offers"]}
        self.assertEqual(set(offers), {std.name, bf.name})
        q = website.get_quote(self.rt, str(self.ci), str(self.co), adults=2, rate_plan=bf.name)
        # 5000 - 10% = 4500/night; 1 extra adult x 700; 3 nights
        self.assertEqual(q["nightly_rate"], 4500)
        self.assertEqual(q["room_charges"], 13500)
        self.assertEqual(q["extra_guest_charges"], 2100)
        self.assertEqual(q["total"], 15600)
        self.assertEqual(q["meal_plan"], "Breakfast Included")
        self.assertRaises(frappe.ValidationError, website.get_quote, self.rt, str(self.ci), str(self.co), 2,
                          rate_plan="NOT-A-PLAN")
        # a plan that does not cover the whole stay is not offered
        self.assertRaises(frappe.ValidationError, website.get_quote, self.rt, str(self.ci), str(add_days(self.co, 3)), 2,
                          rate_plan=std.name)

    def test_booking_creates_real_reservation_ignoring_client_price(self):
        _, bf = self.make_plans()
        res = self.book(rate_plan=bf.name, total=1, rate=1, estimated_total=1, special_requests="<b>Late</b> arrival")
        self.assertEqual(len(res["booking_references"]), 1)
        self.assertEqual(res["status"], "Reserved")
        self.assertEqual(res["total"], 15600)
        name = res["booking_references"][0]
        frappe.set_user("Administrator")
        doc = frappe.get_doc("Hotel Reservation", name)
        self.assertEqual((doc.room_type, doc.rate_plan, doc.adults, doc.status), (self.rt, bf.name, 2, "Reserved"))
        self.assertIn(doc.room, self.rooms)
        self.assertEqual(doc.stays[0].rate, 5200)  # 4500 + 700 extra adult, server computed
        self.assertEqual(doc.estimated_total, 15600)
        self.assertIn("Late arrival", doc.remarks)
        self.assertNotIn("<b>", doc.remarks)
        cust = frappe.get_doc("Customer", doc.customer)
        self.assertEqual((cust.customer_name, cust.is_hotel_guest, cust.email_id), ("Wt Guest", 1, "wt.guest@example.com"))
        # visible in Front Desk Console data for the arrival date
        from hospitality_core.api.console import get_console_data
        self.assertIn(name, json.dumps(get_console_data(target_date=str(self.ci)), default=str))

    def test_multi_room_booking_and_customer_reuse(self):
        res = self.book(rooms=2, adults=3, children=1, email="Wt.Multi@Example.com")
        self.assertEqual(len(res["booking_references"]), 2)
        frappe.set_user("Administrator")
        docs = [frappe.get_doc("Hotel Reservation", n) for n in res["booking_references"]]
        self.assertEqual({d.room for d in docs}, set(self.rooms))
        self.assertEqual(sorted((d.adults, d.children) for d in docs), [(1, 1), (2, 0)])
        self.assertEqual(len({d.customer for d in docs}), 1)
        frappe.set_user("Guest")
        self.assertFalse(self.search()[self.rt]["available"])
        # the same email on another stay reuses the existing guest Customer
        res2 = self.book(check_in=str(add_days(self.co, 5)), check_out=str(add_days(self.co, 6)), email="wt.multi@example.com")
        frappe.set_user("Administrator")
        self.assertEqual(frappe.db.get_value("Hotel Reservation", res2["booking_references"][0], "customer"), docs[0].customer)

    # ---------- E: duplicates, conflicts, validation ----------
    def test_duplicate_submissions(self):
        token = "wt-dup-token-0000000001"
        first = self.book(booking_token=token)
        # same token while the original request is uncommitted -> "processing", never a second reservation
        self.assertRaises(website.BookingUnavailable, self.book, booking_token=token)
        # same guest/stay with a new token (e.g. page reload) returns the existing reservation
        again = self.book()
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["booking_references"], first["booking_references"])
        frappe.set_user("Administrator")
        self.assertEqual(frappe.db.count("Hotel Reservation", {"room_type": self.rt}), 1)
        frappe.cache.delete(website._cache_key(token))

    def test_completed_token_returns_stored_result(self):
        token = "wt-done-token-000000001"
        frappe.cache.set(website._cache_key(token), json.dumps({"booking_references": ["HR-X"]}), ex=60)
        self.assertEqual(self.book(booking_token=token)["booking_references"], ["HR-X"])
        frappe.cache.delete(website._cache_key(token))

    def test_sold_out_and_race_recheck(self):
        self.book(email="a@example.com")
        self.book(email="b@example.com")
        self.assertRaises(website.BookingUnavailable, self.book, email="c@example.com")
        # if availability came from a stale snapshot, the locking re-check still refuses booked rooms
        with mock.patch.object(website, "_bookable_rooms", return_value=list(self.rooms)):
            self.assertRaises(website.BookingUnavailable, self.book, email="d@example.com")

    def test_input_validation(self):
        past = str(add_days(getdate(), -1))
        bad = [
            dict(check_in=past),
            dict(check_out=str(self.ci)),
            dict(check_out=str(add_days(self.ci, -1))),
            dict(check_in="not-a-date"),
            dict(check_out=str(add_days(self.ci, 31))),
            dict(check_in=str(add_days(getdate(), 400)), check_out=str(add_days(getdate(), 401))),
            dict(adults=0),
            dict(adults=-1),
            dict(adults="two"),
            dict(adults=3),               # over max_adults for one room
            dict(adults=2, children=2),   # over occupancy
            dict(rooms=0),
            dict(rooms=6, adults=6),
            dict(rooms=2, adults=1),
            dict(room_type="No Such Room"),
            dict(rate_plan="No Such Plan"),
            dict(guest_name=""),
            dict(guest_name="<script>"),
            dict(email="not-an-email"),
            dict(phone="abc"),
            dict(booking_token="short"),
        ]
        for kw in bad:
            with self.subTest(kw=kw), self.assertRaises((frappe.ValidationError, frappe.DoesNotExistError)):
                self.book(**kw)
        frappe.set_user("Administrator")
        hidden = self.make_room_type("Draft", published=0, default_rate=100)
        frappe.get_doc({"doctype": "Hotel Room", "room_number": "WT-9", "room_type": hidden}).insert()
        frappe.set_user("Guest")
        self.assertRaises(frappe.DoesNotExistError, self.book, room_type=hidden)
        frappe.set_user("Administrator")
        self.assertEqual(frappe.db.count("Hotel Reservation", {"room_type": ["in", [self.rt, hidden]]}), 0)

    def test_room_type_without_price_not_bookable(self):
        frappe.set_user("Administrator")
        free = self.make_room_type("NoPrice", default_rate=0)
        frappe.get_doc({"doctype": "Hotel Room", "room_number": "WT-8", "room_type": free}).insert()
        frappe.set_user("Guest")
        r = self.search()[free]
        self.assertFalse(r["available"])
        self.assertEqual(r["offers"], [])
        self.assertRaises(frappe.ValidationError, self.book, room_type=free)

    def test_taxes_use_configured_template(self):
        frappe.set_user("Administrator")
        company = frappe.db.get_single_value("Hotel Settings", "company")
        account = frappe.db.get_value("Account", {"company": company, "account_type": "Tax", "is_group": 0}, "name")
        if not account:
            self.skipTest("no Tax account in the hotel company to build a test template")
        template = frappe.get_doc({"doctype": "Sales Taxes and Charges Template", "title": "_WT GST 12", "company": company,
                                   "taxes": [{"charge_type": "On Net Total", "account_head": account, "rate": 12,
                                              "description": "GST 12%"}]}).insert()
        frappe.db.set_single_value("Hotel Settings", "sales_taxes_template", template.name)
        frappe.set_user("Guest")
        q = website.get_quote(self.rt, str(self.ci), str(self.co), adults=1)
        self.assertTrue(q["taxes_configured"])
        self.assertEqual(q["net_total"], 15000)
        self.assertEqual(q["taxes"], 1800)
        self.assertEqual(q["total"], 16800)
        self.assertEqual(q["tax_breakdown"][0]["description"], "GST 12%")
        res = self.book(adults=1, total=0)
        self.assertEqual(res["total"], 16800)
        frappe.set_user("Administrator")
        self.assertEqual(frappe.db.get_value("Hotel Reservation", res["booking_references"][0], "estimated_total"), 16800)
