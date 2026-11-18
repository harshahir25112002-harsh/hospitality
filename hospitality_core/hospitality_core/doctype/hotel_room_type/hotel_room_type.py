import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from hospitality_core.listing import normalize_images, validate_amenities


class HotelRoomType(Document):
    def before_naming(self):
        self.room_type_name = (self.room_type_name or "").strip()

    def validate(self):
        self.validate_basic_info()
        self.validate_occupancy()
        self.validate_policies()
        self.primary_image = normalize_images(self, "images", require_public=cint(self.is_published))
        validate_amenities(self, "amenities", "Room")
        self.validate_publishing()

    def validate_basic_info(self):
        self.room_type_name = (self.room_type_name or "").strip()
        if not self.room_type_name:
            frappe.throw(_("Room Type Name is required."))
        if self.room_type_code:
            self.room_type_code = self.room_type_code.strip().upper()
        if flt(self.room_area) < 0:
            frappe.throw(_("Room Area cannot be negative."))

    def validate_occupancy(self):
        adults, children = cint(self.max_adults), cint(self.max_children)
        if adults < 1:
            frappe.throw(_("Max Adults must be at least 1."))
        if children < 0:
            frappe.throw(_("Max Children cannot be negative."))
        if not self.max_occupancy:
            self.max_occupancy = adults + children
        occupancy = cint(self.max_occupancy)
        if occupancy <= 0:
            frappe.throw(_("Maximum Occupancy must be greater than zero."))
        if adults > occupancy:
            frappe.throw(_("Max Adults ({0}) cannot exceed Maximum Occupancy ({1}).").format(adults, occupancy))
        if occupancy > adults + children:
            frappe.throw(_("Maximum Occupancy ({0}) cannot exceed Max Adults + Max Children ({1}).").format(
                occupancy, adults + children))

    def validate_policies(self):
        self.smoking_allowed = 1 if self.smoking_policy in ("Smoking", "Designated Smoking Area") else 0
        if cint(self.max_extra_beds) < 0:
            frappe.throw(_("Maximum Extra Beds cannot be negative."))
        if not cint(self.extra_bed_allowed):
            self.max_extra_beds = 0
        elif cint(self.max_extra_beds) < 1:
            frappe.throw(_("Set Maximum Extra Beds when Extra Bed Allowed is enabled."))
        if not cint(self.children_allowed) and cint(self.max_children):
            frappe.throw(_("Max Children must be 0 when Children Allowed is disabled."))

    def validate_publishing(self):
        if not cint(self.is_published):
            return
        missing = []
        if not cint(self.is_active):
            frappe.throw(_("An inactive room type cannot be published."))
        if not self.description:
            missing.append(_("Short Description"))
        if not self.bed_configuration:
            missing.append(_("Bed Configuration"))
        if not self.primary_image:
            missing.append(_("at least one active photograph"))
        if missing:
            frappe.throw(_("Before publishing, provide: {0}").format(", ".join(missing)))
        if not cint(frappe.db.get_single_value("Hotel Settings", "is_active")):
            frappe.throw(_("Room types cannot be published while the property is inactive in Hotel Settings."))

    def on_trash(self):
        reservations = frappe.db.count("Hotel Reservation", {"room_type": self.name}) + frappe.db.count(
            "Hotel Reservation Stay", {"room_type": self.name})
        if reservations:
            frappe.throw(_("Room Type {0} has reservations and cannot be deleted. Mark it inactive instead.").format(
                frappe.bold(self.name)), frappe.LinkExistsError)
