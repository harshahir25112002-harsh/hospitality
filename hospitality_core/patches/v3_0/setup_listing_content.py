import frappe

from hospitality_core.setup.install import setup_default_amenities


def execute():
    setup_default_amenities()
    # back-fill new Room Type fields on existing records without touching existing values
    frappe.db.sql("""UPDATE `tabHotel Room Type`
        SET max_occupancy = IFNULL(max_adults, 0) + IFNULL(max_children, 0)
        WHERE IFNULL(max_occupancy, 0) = 0""")
    frappe.db.sql("UPDATE `tabRoom Rate Plan` SET meal_plan = 'Room Only' WHERE IFNULL(meal_plan, '') = ''")
    if not frappe.db.exists("Singles", {"doctype": "Hotel Settings", "field": "is_active"}):
        frappe.db.set_single_value("Hotel Settings", "is_active", 1)
