"""Add Razorpay navigation to the live 'Hospitality Core' sidebar without overwriting it.

The sidebar on sites is customised in the database (it differs from the JSON in the app), so the
items are inserted in place instead of re-syncing the JSON. Idempotent."""
import frappe

ITEMS = [
    # (after label, item)
    ("Hotel Settings", {"label": "Payment Gateway", "type": "Link", "link_type": "DocType",
                        "link_to": "Hotel Payment Gateway Settings", "icon": "credit-card", "child": 0}),
    (None, {"label": "Online Payments", "type": "Link", "link_type": "Page",
            "link_to": "hotel-payment-dashboard", "icon": "wallet", "child": 1}),
]


def execute():
    if not frappe.db.exists("Sidebar", "Hospitality Core"):
        return
    doc = frappe.get_doc("Sidebar", "Hospitality Core")
    rows = [r.as_dict() for r in doc.items]
    existing = {r.get("link_to") for r in rows}
    changed = False
    for after, item in ITEMS:
        if item["link_to"] in existing:
            continue
        pos = next((i + 1 for i, r in enumerate(rows) if r.get("label") == after), len(rows)) if after else len(rows)
        rows.insert(pos, item)
        changed = True
    if not changed:
        return
    doc.set("items", [])
    for r in rows:
        r = {k: v for k, v in r.items() if k not in ("name", "idx", "parent", "parenttype", "parentfield", "doctype",
                                                     "creation", "modified", "owner", "modified_by", "docstatus")}
        doc.append("items", r)
    doc.flags.ignore_permissions = True
    doc.save()
