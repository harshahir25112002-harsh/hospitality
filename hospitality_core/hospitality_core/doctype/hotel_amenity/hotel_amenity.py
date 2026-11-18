import frappe
from frappe import _
from frappe.model.document import Document


class HotelAmenity(Document):
    def validate(self):
        self.amenity_name = (self.amenity_name or "").strip()
        if not self.amenity_name:
            frappe.throw(_("Amenity Name is required."))
        if self.amenity_code:
            self.amenity_code = self.amenity_code.strip().upper().replace(" ", "_")
