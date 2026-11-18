# Copyright (c) 2026, Sky Hotel Management and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestHotelSettings(IntegrationTestCase):
	"""Integration tests for HotelSettings — cover image clear/delete fix."""

	def _ensure_test_file(self, file_url="/files/test_cover_image.jpg"):
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
		return file_url

	def _add_property_image_row(self, settings, file_url):
		"""Add a property image row to the gallery table."""
		settings.append("property_images", {
			"image": file_url,
			"image_caption": "Test Image",
			"is_primary_image": 1,
			"is_active": 1,
			"display_order": 1,
		})

	def test_clear_cover_image_field_stays_empty(self):
		"""Clicking Clear empties the field — validate must not re-populate it."""
		file_url = self._ensure_test_file()
		settings = frappe.get_single("Hotel Settings")

		# Add a gallery image so normalize_images returns a primary
		if not settings.property_images:
			self._add_property_image_row(settings, file_url)

		# Set cover_image and save to establish a baseline
		settings.cover_image = file_url
		settings.save(ignore_permissions=True)

		# Now simulate the Clear button: set cover_image to None and save
		settings.reload()
		settings.cover_image = None
		settings.save(ignore_permissions=True)

		# After save, cover_image must remain empty (not re-populated by validate)
		settings.reload()
		self.assertFalse(
			settings.cover_image,
			"cover_image should remain empty after the user cleared it"
		)

	def test_clearing_field_does_not_delete_file_record(self):
		"""Clearing the cover_image field should NOT delete the File record."""
		file_url = self._ensure_test_file("/files/test_nodelete.jpg")
		settings = frappe.get_single("Hotel Settings")

		if not settings.property_images:
			self._add_property_image_row(settings, file_url)

		settings.cover_image = file_url
		settings.save(ignore_permissions=True)

		# Clear the field
		settings.reload()
		settings.cover_image = None
		settings.save(ignore_permissions=True)

		# The File record must still exist
		self.assertTrue(
			frappe.db.exists("File", {"file_url": file_url}),
			"File record should still exist after clearing the field"
		)

	def test_save_preserves_empty_field(self):
		"""After clearing and saving, re-saving should keep the field empty."""
		file_url = self._ensure_test_file("/files/test_preserve_empty.jpg")
		settings = frappe.get_single("Hotel Settings")

		if not settings.property_images:
			self._add_property_image_row(settings, file_url)

		settings.cover_image = file_url
		settings.save(ignore_permissions=True)

		# Clear and save
		settings.reload()
		settings.cover_image = None
		settings.save(ignore_permissions=True)

		# Save again (no changes) — field must stay empty
		settings.reload()
		settings.save(ignore_permissions=True)
		settings.reload()
		self.assertFalse(
			settings.cover_image,
			"cover_image should stay empty on subsequent saves"
		)

	def test_upload_replacement_image(self):
		"""Uploading a new image to cover_image after clearing should work."""
		file_url_1 = self._ensure_test_file("/files/test_replace_1.jpg")
		file_url_2 = self._ensure_test_file("/files/test_replace_2.jpg")
		settings = frappe.get_single("Hotel Settings")

		if not settings.property_images:
			self._add_property_image_row(settings, file_url_1)

		settings.cover_image = file_url_1
		settings.save(ignore_permissions=True)

		# Clear
		settings.reload()
		settings.cover_image = None
		settings.save(ignore_permissions=True)

		# Upload replacement
		settings.reload()
		settings.cover_image = file_url_2
		settings.save(ignore_permissions=True)

		settings.reload()
		self.assertEqual(settings.cover_image, file_url_2)

	def test_auto_populate_cover_when_never_set(self):
		"""When cover_image was never set, validate should auto-populate from gallery."""
		file_url = self._ensure_test_file("/files/test_auto_pop.jpg")
		settings = frappe.get_single("Hotel Settings")

		# Remove all gallery images and cover
		settings.property_images = []
		settings.cover_image = None
		settings.flags.ignore_validate = True
		settings.save(ignore_permissions=True)

		# Now add a gallery image while cover_image is empty
		settings.reload()
		self._add_property_image_row(settings, file_url)
		settings.cover_image = None
		settings.flags.ignore_validate = False
		settings.save(ignore_permissions=True)

		settings.reload()
		self.assertEqual(
			settings.cover_image, file_url,
			"cover_image should be auto-populated from gallery primary when never set"
		)

	def test_hotel_logo_clear_works(self):
		"""Clearing hotel_logo should work without interference from cover_image logic."""
		file_url = self._ensure_test_file("/files/test_logo.jpg")
		settings = frappe.get_single("Hotel Settings")

		settings.hotel_logo = file_url
		settings.save(ignore_permissions=True)

		settings.reload()
		settings.hotel_logo = None
		settings.save(ignore_permissions=True)

		settings.reload()
		self.assertFalse(
			settings.hotel_logo,
			"hotel_logo should remain empty after clearing"
		)
