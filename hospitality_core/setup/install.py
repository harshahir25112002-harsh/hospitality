import frappe
from hospitality_core.setup.custom_fields import setup_custom_fields


def after_install():
    setup_custom_fields()
    setup_default_amenities()



def setup_default_amenities():
    """Insert sample amenities from setup/default_amenities.json; existing records are never modified."""
    import json
    import os

    import frappe

    with open(os.path.join(os.path.dirname(__file__), "default_amenities.json")) as f:
        rows = json.load(f)
    for row in rows:
        if frappe.db.exists("Hotel Amenity", row["amenity_name"]) or frappe.db.exists(
                "Hotel Amenity", {"amenity_code": row["amenity_code"]}):
            continue
        frappe.get_doc({"doctype": "Hotel Amenity", "is_active": 1, **row}).insert(ignore_permissions=True)
