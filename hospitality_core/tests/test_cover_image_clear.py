"""
Quick test script for the cover_image clear fix.
Run with: bench --site frappe.com execute hospitality_core.tests.test_cover_image_clear.run
"""
import frappe


def _ensure_test_file(file_url="/files/test_cover_fix.jpg"):
    """Create a File record for testing if it doesn't exist."""
    if not frappe.db.exists("File", {"file_url": file_url}):
        f = frappe.get_doc({
            "doctype": "File",
            "file_name": file_url.split("/")[-1],
            "file_url": file_url,
            "attached_to_doctype": "Hotel Settings",
            "attached_to_name": "Hotel Settings",
            "is_private": 0,
        })
        f.insert(ignore_permissions=True)
        frappe.db.commit()
    return file_url


def _add_property_image_row(settings, file_url):
    """Add a property image row to the gallery table."""
    settings.append("property_images", {
        "image": file_url,
        "image_caption": "Test Image",
        "is_primary_image": 1,
        "is_active": 1,
        "display_order": 1,
    })


def run():
    """Run all cover_image clear tests."""
    results = []

    # Test 1: Clearing cover_image field stays empty after save
    try:
        file_url = _ensure_test_file("/files/test_clear_stays_empty.jpg")
        settings = frappe.get_single("Hotel Settings")

        # Ensure gallery has an image
        if not settings.property_images:
            _add_property_image_row(settings, file_url)

        settings.cover_image = file_url
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        # Simulate Clear button: set cover_image to None, save
        settings.reload()
        settings.cover_image = None
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        settings.reload()
        assert not settings.cover_image, f"FAIL: cover_image should be empty, got '{settings.cover_image}'"
        results.append("PASS: test_clear_cover_image_stays_empty")
    except Exception as e:
        results.append(f"FAIL: test_clear_cover_image_stays_empty — {e}")

    # Test 2: Clearing field does NOT delete File record
    try:
        file_url = _ensure_test_file("/files/test_nodelete_file.jpg")
        settings = frappe.get_single("Hotel Settings")
        settings.cover_image = file_url
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        settings.reload()
        settings.cover_image = None
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        assert frappe.db.exists("File", {"file_url": file_url}), "FAIL: File record was deleted"
        results.append("PASS: test_clearing_field_does_not_delete_file")
    except Exception as e:
        results.append(f"FAIL: test_clearing_field_does_not_delete_file — {e}")

    # Test 3: Save preserves empty field on subsequent saves
    try:
        settings = frappe.get_single("Hotel Settings")
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        settings.reload()
        assert not settings.cover_image, f"FAIL: cover_image re-populated on second save, got '{settings.cover_image}'"
        results.append("PASS: test_save_preserves_empty_field")
    except Exception as e:
        results.append(f"FAIL: test_save_preserves_empty_field — {e}")

    # Test 4: Upload replacement image works
    try:
        file_url_2 = _ensure_test_file("/files/test_replacement.jpg")
        settings = frappe.get_single("Hotel Settings")
        settings.cover_image = file_url_2
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        settings.reload()
        assert settings.cover_image == file_url_2, f"FAIL: expected '{file_url_2}', got '{settings.cover_image}'"
        results.append("PASS: test_upload_replacement_image")
    except Exception as e:
        results.append(f"FAIL: test_upload_replacement_image — {e}")

    # Test 5: Auto-populate works when cover was never set
    try:
        file_url = _ensure_test_file("/files/test_auto_populate.jpg")
        settings = frappe.get_single("Hotel Settings")
        settings.property_images = []
        settings.cover_image = None
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        settings.reload()
        _add_property_image_row(settings, file_url)
        settings.cover_image = None
        settings.flags.ignore_validate = False
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        settings.reload()
        assert settings.cover_image == file_url, f"FAIL: expected auto-populated '{file_url}', got '{settings.cover_image}'"
        results.append("PASS: test_auto_populate_when_never_set")
    except Exception as e:
        results.append(f"FAIL: test_auto_populate_when_never_set — {e}")

    # Test 6: hotel_logo clear works independently
    try:
        file_url = _ensure_test_file("/files/test_logo_clear.jpg")
        settings = frappe.get_single("Hotel Settings")
        settings.hotel_logo = file_url
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        settings.reload()
        settings.hotel_logo = None
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        settings.reload()
        assert not settings.hotel_logo, f"FAIL: hotel_logo should be empty, got '{settings.hotel_logo}'"
        results.append("PASS: test_hotel_logo_clear")
    except Exception as e:
        results.append(f"FAIL: test_hotel_logo_clear — {e}")

    print("\n" + "=" * 60)
    print("COVER IMAGE CLEAR FIX — TEST RESULTS")
    print("=" * 60)
    for r in results:
        print(r)
    passed = sum(1 for r in results if r.startswith("PASS"))
    total = len(results)
    print(f"\n{passed}/{total} tests passed")
    print("=" * 60)
