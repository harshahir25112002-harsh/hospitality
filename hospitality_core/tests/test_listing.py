"""
Room type listing content, amenities, property profile and rate plan compatibility.
Runs inside a rolled-back test transaction; uploaded test files are removed in tearDownClass.
"""
import io

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate



def png(seed):
    # distinct content per file: Frappe de-duplicates uploads with identical content
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (seed * 40 % 256, 90, 160)).save(buf, format="PNG")
    return buf.getvalue()

PREFIX = "_TL "


class TestHotelListing(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.files = [cls.make_file(f"tl_img_{i}.png", i) for i in range(3)]
        cls.private_file = cls.make_file("tl_private.png", 5, is_private=1)
        cls.amenities = [cls.make_amenity(f"{PREFIX}Amenity {i}", f"TL_AM_{i}") for i in range(3)]
        cls.property_amenity = cls.make_amenity(f"{PREFIX}Pool", "TL_POOL", applies_to="Property")
        cls.inactive_amenity = cls.make_amenity(f"{PREFIX}Inactive", "TL_INACTIVE", is_active=0)

    @classmethod
    def tearDownClass(cls):
        frappe.set_user("Administrator")
        for f in cls.files + [cls.private_file]:
            frappe.delete_doc("File", frappe.db.get_value("File", {"file_url": f}), force=True, ignore_permissions=True)
        super().tearDownClass()

    @staticmethod
    def make_file(name, seed, is_private=0):
        return frappe.get_doc({"doctype": "File", "file_name": name, "content": png(seed),
                               "is_private": is_private}).insert(ignore_permissions=True).file_url

    @staticmethod
    def make_amenity(name, code, applies_to="Room and Property", is_active=1):
        return frappe.get_doc({"doctype": "Hotel Amenity", "amenity_name": name, "amenity_code": code,
                               "category": "General", "icon_name": "star", "applies_to": applies_to,
                               "is_active": is_active}).insert().name

    def setUp(self):
        frappe.set_user("Administrator")
        frappe.db.set_single_value("Hotel Settings", "is_active", 1)
        frappe.clear_document_cache("Hotel Settings", "Hotel Settings")

    def room_type(self, name="Deluxe", **kw):
        doc = {"doctype": "Hotel Room Type", "room_type_name": f"{PREFIX}{self._testMethodName[5:25]} {name}", "default_rate": 2500,
               "max_adults": 2, "max_children": 1}
        doc.update(kw)
        return frappe.get_doc(doc)

    def images(self, *specs):
        return [{"image": self.files[i], "image_caption": f"Photo {i}", "image_category": "Bedroom", **extra}
                for i, extra in specs]

    # ---------- room type ----------
    def test_room_type_create_and_update(self):
        rt = self.room_type(room_type_code="dlx", room_area=320, bed_configuration="King Bed",
                            room_view="Sea View", detailed_description="<p>Large</p>")
        rt.insert()
        self.assertEqual(rt.room_type_code, "DLX")
        self.assertEqual(rt.max_occupancy, 3)  # defaulted from adults + children
        self.assertEqual(rt.smoking_allowed, 0)
        rt.room_view, rt.smoking_policy, rt.max_occupancy = "Pool View", "Smoking", 2
        rt.save()
        rt.reload()
        self.assertEqual((rt.room_view, rt.smoking_allowed, rt.max_occupancy), ("Pool View", 1, 2))

    def test_occupancy_and_area_validation(self):
        for kw in ({"max_adults": 0}, {"max_children": -1}, {"max_occupancy": -2},
                   {"max_occupancy": 5}, {"max_adults": 3, "max_occupancy": 2}, {"room_area": -1},
                   {"children_allowed": 0}):
            with self.subTest(kw=kw), self.assertRaises(frappe.ValidationError):
                self.room_type(name=f"Occ {kw}", **kw).insert()

    def test_required_fields_and_extra_beds(self):
        with self.assertRaises(frappe.ValidationError):
            self.room_type(room_type_name="   ").insert()
        with self.assertRaises(frappe.ValidationError):
            self.room_type(name="EB1", extra_bed_allowed=1, max_extra_beds=0).insert()
        with self.assertRaises(frappe.ValidationError):
            self.room_type(name="EB2", extra_bed_allowed=1, max_extra_beds=-1).insert()
        rt = self.room_type(name="EB3", extra_bed_allowed=0, max_extra_beds=4).insert()
        self.assertEqual(rt.max_extra_beds, 0)
        rt = self.room_type(name="EB4", extra_bed_allowed=1, max_extra_beds=2, pets_allowed=1,
                            check_in_instructions="ID required", room_restrictions="No parties").insert()
        self.assertEqual((rt.max_extra_beds, rt.pets_allowed), (2, 1))

    # ---------- images ----------
    def test_multiple_images_auto_primary_and_order(self):
        rt = self.room_type(images=self.images((0, {"display_order": 2}), (1, {"display_order": 1}), (2, {})))
        rt.insert()
        self.assertEqual(len(rt.images), 3)
        # lowest display order wins when no primary is chosen
        self.assertEqual(rt.primary_image, self.files[1])
        self.assertEqual([r.is_primary_image for r in rt.images], [0, 1, 0])
        self.assertEqual(rt.images[2].display_order, 3)  # defaulted from row position

    def test_change_primary_image(self):
        rt = self.room_type(images=self.images((0, {"is_primary_image": 1}), (1, {}))).insert()
        self.assertEqual(rt.primary_image, self.files[0])
        rt.images[0].is_primary_image, rt.images[1].is_primary_image = 0, 1
        rt.save()
        self.assertEqual(rt.primary_image, self.files[1])
        # deactivating the primary image moves primary to the next active one
        rt.images[1].is_active = 0
        rt.save()
        self.assertEqual(rt.primary_image, self.files[0])
        self.assertEqual(rt.images[1].is_primary_image, 0)

    def test_duplicate_primary_blocked(self):
        rt = self.room_type(images=self.images((0, {"is_primary_image": 1}), (1, {"is_primary_image": 1})))
        self.assertRaises(frappe.ValidationError, rt.insert)

    def test_image_reference_validation(self):
        rt = self.room_type(images=[{"image": "/files/does-not-exist-tl.png"}])
        self.assertRaises(frappe.ValidationError, rt.insert)
        rt = self.room_type(name="Dup", images=self.images((0, {}), (0, {})))
        self.assertRaises(frappe.ValidationError, rt.insert)

    # ---------- amenities ----------
    def test_amenity_master_and_assignment(self):
        self.assertEqual(frappe.db.get_value("Hotel Amenity", self.amenities[0], "amenity_code"), "TL_AM_0")
        rt = self.room_type(amenities=[{"amenity": a} for a in self.amenities]).insert()
        self.assertEqual(len(rt.amenities), 3)
        self.assertEqual(rt.amenities[0].icon_name, "star")
        self.assertEqual(rt.amenities[0].is_available, 1)

    def test_duplicate_and_inactive_amenity_blocked(self):
        rt = self.room_type(amenities=[{"amenity": self.amenities[0]}, {"amenity": self.amenities[0]}])
        self.assertRaises(frappe.ValidationError, rt.insert)
        rt = self.room_type(name="Inactive", amenities=[{"amenity": self.inactive_amenity}])
        self.assertRaises(frappe.ValidationError, rt.insert)
        rt = self.room_type(name="Scope", amenities=[{"amenity": self.property_amenity}])
        self.assertRaises(frappe.ValidationError, rt.insert)

    def test_existing_assignment_survives_amenity_deactivation(self):
        rt = self.room_type(amenities=[{"amenity": self.amenities[1]}]).insert()
        frappe.db.set_value("Hotel Amenity", self.amenities[1], "is_active", 0)
        rt.reload()
        rt.room_area = 100
        rt.save()  # keeping the old row is allowed
        rt.append("amenities", {"amenity": self.amenities[2]})
        rt.save()
        frappe.db.set_value("Hotel Amenity", self.amenities[2], "is_active", 0)
        rt.reload()
        rt.amenities = [rt.amenities[0]]
        rt.save()
        rt.append("amenities", {"amenity": self.amenities[2]})  # re-adding an inactive one is new
        self.assertRaises(frappe.ValidationError, rt.save)

    # ---------- publishing ----------
    def test_room_type_publishing_rules(self):
        rt = self.room_type(is_published=1)
        self.assertRaises(frappe.ValidationError, rt.insert)  # no description / bed / image
        rt = self.room_type(name="Pub", is_published=1, description="Nice", bed_configuration="Queen Bed",
                            images=[{"image": self.private_file}])
        self.assertRaises(frappe.ValidationError, rt.insert)  # private image
        rt = self.room_type(name="Pub2", is_published=1, description="Nice", bed_configuration="Queen Bed",
                            images=self.images((0, {})))
        rt.insert()
        self.assertEqual(rt.primary_image, self.files[0])
        rt.is_active = 0
        self.assertRaises(frappe.ValidationError, rt.save)
        frappe.db.set_single_value("Hotel Settings", "is_active", 0)
        rt.reload()
        rt.room_area = 10
        self.assertRaises(frappe.ValidationError, rt.save)

    def test_room_type_with_reservation_not_deleted(self):
        rt = self.room_type(name="Del").insert()
        frappe.get_doc({"doctype": "Hotel Room", "room_number": "TL-901", "room_type": rt.name}).insert()
        customer = frappe.get_all("Customer", limit=1, pluck="name")[0]
        frappe.get_doc({"doctype": "Hotel Reservation", "customer": customer, "room_type": rt.name,
                        "room": "TL-901", "check_in_date": add_days(nowdate(), 400),
                        "check_out_date": add_days(nowdate(), 401), "adults": 1}).insert()
        self.assertRaises(frappe.LinkExistsError, frappe.delete_doc, "Hotel Room Type", rt.name)
        self.assertTrue(frappe.db.exists("Hotel Room Type", rt.name))
        unused = self.room_type(name="Unused").insert()
        frappe.delete_doc("Hotel Room Type", unused.name)
        self.assertFalse(frappe.db.exists("Hotel Room Type", unused.name))

    # ---------- property profile ----------
    def settings(self):
        return frappe.get_doc("Hotel Settings")

    def test_property_profile_images_and_amenities(self):
        s = self.settings()
        s.update({"hotel_name": "Sky Test Hotel", "property_short_description": "Central", "star_rating": "4",
                  "city": "Pune", "country": "India", "address_line": "1 Main Road", "latitude": 18.52,
                  "longitude": 73.85, "email_address": "desk@example.com"})
        s.set("property_images", [{"image": self.files[0], "image_category": "Exterior"},
                                  {"image": self.files[1], "image_category": "Lobby", "is_primary_image": 1}])
        s.set("property_amenities", [{"amenity": self.property_amenity}, {"amenity": self.amenities[0]}])
        s.save()
        s = self.settings()
        self.assertEqual(s.website_slug, "sky-test-hotel")
        self.assertEqual(len(s.property_images), 2)
        self.assertEqual(s.cover_image, self.files[1])
        self.assertEqual(len(s.property_amenities), 2)
        s.append("property_amenities", {"amenity": self.property_amenity})
        self.assertRaises(frappe.ValidationError, s.save)
        s = self.settings()
        s.latitude = 95
        self.assertRaises(frappe.ValidationError, s.save)
        s = self.settings()
        s.website_slug = "Bad Slug!"
        self.assertRaises(frappe.ValidationError, s.save)
        s = self.settings()
        s.property_images[0].is_primary_image = 1
        self.assertRaises(frappe.ValidationError, s.save)

    def test_property_publishing_validation(self):
        s = self.settings()
        s.update({"is_published": 1, "hotel_name": None, "property_short_description": None})
        s.set("property_images", [])
        self.assertRaises(frappe.ValidationError, s.save)
        s = self.settings()
        s.update({"is_published": 1, "hotel_name": "Sky Pub", "property_short_description": "Short",
                  "address_line": "Road", "city": "Pune", "country": "India", "contact_number": "+91-9999999999",
                  "is_active": 1})
        s.set("property_images", [{"image": self.files[2]}])
        s.save()
        self.assertEqual(self.settings().is_published, 1)
        s = self.settings()
        s.is_active = 0
        self.assertRaises(frappe.ValidationError, s.save)

    # ---------- rate plans ----------
    def test_rate_plan_meal_plans_coexist_and_validate(self):
        rt = self.room_type(name="Rates").insert()
        start, end = add_days(nowdate(), 300), add_days(nowdate(), 330)

        def plan(name, **kw):
            return frappe.get_doc({"doctype": "Room Rate Plan", "plan_name": f"{PREFIX}{name}", "room_type": rt.name,
                                   "rate": 3000, "valid_from": start, "valid_to": end, "active": 1, **kw})

        std = plan("Standard").insert()
        self.assertEqual((std.meal_plan, std.is_refundable), ("Room Only", 1))
        plan("Breakfast", meal_plan="Breakfast Included", rate=3500, free_cancellation=1,
             free_cancellation_hours=24, cancellation_policy="Free until 24h").insert()
        for mp in ("Breakfast + Lunch", "Breakfast + Dinner", "Full Board"):
            plan(mp, meal_plan=mp, rate=4000).insert()
        nr = plan("NonRef", is_refundable=0, free_cancellation=1, rate=2700).insert()
        self.assertEqual(nr.free_cancellation, 0)
        self.assertRaises(frappe.ValidationError, plan("Std Dup").insert)  # same product overlaps
        self.assertRaises(frappe.ValidationError, plan("Disc", meal_plan="Full Board", is_refundable=0,
                                                       discount_percentage=150).insert)
        self.assertRaises(frappe.ValidationError, plan("Neg", meal_plan="Full Board", is_refundable=0,
                                                       extra_adult_charge=-1).insert)
        from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import get_room_rate
        self.assertEqual(get_room_rate(rt.name, add_days(start, 1)), 2700)  # unchanged: cheapest generic plan

    # ---------- permissions ----------
    def test_configuration_permissions(self):
        has = frappe.permissions.has_permission
        self.assertTrue(has("Hotel Amenity", "write", user="Administrator"))
        for role, can_write in (("Hospitality Manager", True), ("Hospitality User", False)):
            perms = {p.role: p for p in frappe.get_meta("Hotel Amenity").permissions}
            self.assertEqual(bool(perms[role].write), can_write)
            perms = {p.role: p for p in frappe.get_meta("Hotel Settings").permissions}
            self.assertEqual(bool(perms[role].write), can_write)
        self.assertFalse(has("Hotel Settings", "write", user="Guest"))
        self.assertFalse(has("Hotel Amenity", "read", user="Guest"))
        self.assertFalse(has("Hotel Reservation", "read", user="Guest"))
