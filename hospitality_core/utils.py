import frappe
from frappe import _


def get_settings():
    """Returns cached Hotel Settings single doc."""
    return frappe.get_cached_doc("Hotel Settings")


def get_company():
    """Returns default company from Hotel Settings or user defaults."""
    settings = get_settings()
    if settings.company:
        return settings.company
    company = frappe.defaults.get_user_default("Company")
    if not company:
        frappe.throw(_("Please configure default Company in Hotel Settings or User Defaults."))
    return company


def get_room_item(room_type):
    """
    Returns the billable Item code for a room type.
    Falls back to Hotel Settings default_room_item.
    Throws a descriptive error if neither is set.
    """
    item = frappe.db.get_value("Hotel Room Type", room_type, "item")
    if item:
        return item
    settings = get_settings()
    if settings.default_room_item:
        return settings.default_room_item
    frappe.throw(_("No billable Room Item found for Room Type '{0}' or in Hotel Settings.").format(room_type))


def boot_session(bootinfo):
    """Exposes hotel settings to client-side JS."""
    try:
        settings = get_settings()
        bootinfo.hotel_settings = {
            "company": settings.company,
            "default_room_item": settings.default_room_item,
            "guest_customer_group": settings.guest_customer_group,
            "guest_territory": settings.guest_territory,
            "sales_taxes_template": settings.sales_taxes_template,
            "cost_center": settings.cost_center,
            "status_after_maintenance": settings.status_after_maintenance or "Available",
            "allow_checkin_before_arrival": bool(settings.allow_checkin_before_arrival),
            "block_checkout_if_balance": bool(settings.block_checkout_if_balance),
            "balance_tolerance": float(settings.balance_tolerance or 0.0),
            "min_billable_nights": int(settings.min_billable_nights or 1)
        }
    except Exception:
        bootinfo.hotel_settings = {}



def ensure_default_room_item():
    """
    Ensures a billable service item exists for hotel rooms in Hotel Settings.
    Compatible with India Compliance GST requirements (HSN/SAC 996311).
    """
    settings = frappe.get_single("Hotel Settings")
    if settings.default_room_item and frappe.db.exists("Item", settings.default_room_item):
        return settings.default_room_item

    # 1. Check if any non-stock service item already exists in the system
    existing = frappe.db.get_value("Item", {"is_stock_item": 0}, "name")
    if existing:
        settings.default_room_item = existing
        settings.save(ignore_permissions=True)
        return existing

    item_code = "HOTEL-ROOM-NIGHT"
    if frappe.db.exists("Item", item_code):
        settings.default_room_item = item_code
        settings.save(ignore_permissions=True)
        return item_code

    # 2. Check for GST HSN/SAC code (required by india_compliance)
    hsn_code = None
    if frappe.db.table_exists("GST HSN Code"):
        # 996311 is the official SAC code for hotel accommodation services in India
        hsn_code = (
            frappe.db.get_value("GST HSN Code", {"hsn_code": "996311"}, "name")
            or frappe.db.get_value("GST HSN Code", {"name": "996311"}, "name")
            or frappe.db.get_value("GST HSN Code", {"name": ["like", "9963%"]}, "name")
            or frappe.db.get_value("GST HSN Code", {}, "name")
        )
        if not hsn_code:
            try:
                hsn_doc = frappe.get_doc({
                    "doctype": "GST HSN Code",
                    "hsn_code": "996311",
                    "description": "Room or unit accommodation services provided by hotels"
                })
                hsn_doc.flags.ignore_mandatory = True
                hsn_doc.flags.ignore_permissions = True
                hsn_doc.insert()
                hsn_code = hsn_doc.name
            except Exception:
                hsn_code = "996311"

    item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
    item_dict = {
        "doctype": "Item",
        "item_code": item_code,
        "item_name": "Room Night",
        "item_group": item_group,
        "is_stock_item": 0,
        "stock_uom": "Nos",
    }

    if hsn_code:
        item_dict["gst_hsn_code"] = hsn_code

    item_doc = frappe.get_doc(item_dict)
    item_doc.flags.ignore_mandatory = True
    item_doc.flags.ignore_validate = True
    item_doc.flags.ignore_permissions = True
    item_doc.insert()

    settings.default_room_item = item_code
    settings.save(ignore_permissions=True)
    return item_code
