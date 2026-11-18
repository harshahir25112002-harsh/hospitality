"""
Shared validation for hotel listing content (photographs and amenities) used by
Hotel Room Type and Hotel Settings. Images use Frappe's File attachment system:
child rows hold only the file URL; binary data lives in File records.
"""
import os
import re

import frappe
from frappe import _
from frappe.utils import cint

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def slugify(value):
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


# def validate_file_reference(url, label):
#     """A referenced image must be an existing File record (uploaded via Frappe)."""
#     if not url:
#         return
#     if not frappe.db.exists("File", {"file_url": url}):
#         frappe.throw(_("{0}: file {1} was not found. Upload it as an attachment.").format(label, url))

def validate_file_reference(url, label):
    """Internet na links chalshe. Local file hoy to File record ke disk par file hovi joiye."""
    if not url:
        return

    # Internet na (external) image links allow
    if url.startswith(("http://", "https://")):
        return

    # Normal rite upload thayeli file
    if frappe.db.exists("File", {"file_url": url}):
        return

    # File record na hoy pan disk par file hoy to pan chalshe
    if ".." not in url and url.startswith(("/files/", "/private/files/")):
        if url.startswith("/private/"):
            path = frappe.get_site_path(url.lstrip("/"))
        else:
            path = frappe.get_site_path("public", url.lstrip("/"))
        if os.path.exists(path):
            return

    frappe.throw(_("{0}: file {1} was not found. Upload it as an attachment.").format(label, url))


def normalize_images(doc, table_field, require_public=False):
    """Validate image rows, enforce exactly one active primary image and fill display order.

    Returns the primary image URL (or None if there are no active images).
    """
    rows = doc.get(table_field) or []
    seen = set()
    for row in rows:
        label = _("Row {0}").format(row.idx)
        if not row.image:
            frappe.throw(_("{0}: Image is required.").format(label))
        validate_file_reference(row.image, label)
        if require_public and cint(row.is_active) and row.image.startswith("/private/"):
            frappe.throw(_("{0}: private files cannot be published. Upload the image as public.").format(label))
        if row.image in seen:
            frappe.throw(_("{0}: the same image is attached more than once.").format(label))
        seen.add(row.image)
        if cint(row.display_order) < 0:
            frappe.throw(_("{0}: Display Order cannot be negative.").format(label))
        if not cint(row.display_order):
            row.display_order = row.idx
        if not cint(row.is_active):
            row.is_primary_image = 0

    active = sorted((r for r in rows if cint(r.is_active)), key=lambda r: (cint(r.display_order), r.idx))
    primaries = [r for r in active if cint(r.is_primary_image)]
    if len(primaries) > 1:
        frappe.throw(_("Only one image can be marked as primary (rows {0}).").format(
            ", ".join(str(r.idx) for r in primaries)))
    if not active:
        return None
    if not primaries:
        active[0].is_primary_image = 1
        return active[0].image
    return primaries[0].image


def validate_amenities(doc, table_field, scope):
    """No duplicates; inactive or out-of-scope amenities cannot be newly assigned."""
    rows = doc.get(table_field) or []
    before = doc.get_doc_before_save()
    existing = {r.amenity for r in (before.get(table_field) or [])} if before else set()
    seen = set()
    for row in rows:
        if row.amenity in seen:
            frappe.throw(_("Row {0}: amenity {1} is assigned more than once.").format(row.idx, frappe.bold(row.amenity)))
        seen.add(row.amenity)
        if row.amenity in existing:
            continue  # keep historic assignments even if the master was deactivated later
        is_active, applies_to = frappe.db.get_value("Hotel Amenity", row.amenity, ["is_active", "applies_to"]) or (0, None)
        if not cint(is_active):
            frappe.throw(_("Row {0}: amenity {1} is inactive and cannot be assigned.").format(row.idx, frappe.bold(row.amenity)))
        if applies_to and applies_to != "Room and Property" and applies_to != scope:
            frappe.throw(_("Row {0}: amenity {1} applies only to {2}.").format(row.idx, frappe.bold(row.amenity), applies_to))
