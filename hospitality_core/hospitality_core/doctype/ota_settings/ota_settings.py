import requests
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class OTASettings(Document):

	def validate(self):
		if self.enabled and not self.get("api_base_url"):
			frappe.throw(_("API Base URL is required."))
		if self.get("api_base_url"):
			self.api_base_url = str(self.api_base_url).strip().rstrip("/")
		if not self.get("feed_endpoint"):
			self.feed_endpoint = "booking_revisions/feed"
		if not self.get("pull_interval_minutes"):
			self.pull_interval_minutes = 15

	@property
	def environment(self):
		return None

	# Fallbacks in case old code/client calls these
	def set_api_url(self):
		pass

	def set_webhook_url(self):
		pass


def get_ota_settings():
	"""Returns cached OTA Settings single doc."""
	return frappe.get_cached_doc("OTA Settings")


def get_api_headers():
	"""Returns headers for OTA API calls."""
	settings = get_ota_settings()
	if not settings.enabled:
		frappe.throw(_("OTA Sync is disabled in OTA Settings."))
	api_key = settings.get_password("api_key")
	if not api_key:
		frappe.throw(_("API Key is not configured in OTA Settings."))
	return {
		"Content-Type": "application/json",
		"user-api-key": api_key,
		"Authorization": f"Bearer {api_key}"
	}


def get_api_url(endpoint=""):
	"""Builds full URL using the configured API Base URL (no hardcoding)."""
	settings = get_ota_settings()
	base = (settings.api_base_url or "").strip().rstrip("/")
	if not base:
		frappe.throw(_("Please configure the API Base URL in OTA Settings."))
	return f"{base}/{endpoint.lstrip('/')}" if endpoint else base


def log_ota_error(error_message):
	"""Saves the last error to OTA Settings for visibility."""
	try:
		frappe.db.set_single_value("OTA Settings", {
			"last_error": str(error_message)[:500],
			"last_error_at": now_datetime(),
			"connection_status": "Error"
		})
		frappe.db.commit()
	except Exception:
		pass


@frappe.whitelist()
def test_connection():
	"""Tests connection using the configured API Base URL and Key."""
	settings = frappe.get_single("OTA Settings")
	if not settings.api_base_url:
		frappe.throw(_("Please enter the API Base URL."))
	if not settings.api_key:
		frappe.throw(_("Please enter the API Key."))

	headers = get_api_headers()
	url = get_api_url("properties")

	try:
		resp = requests.get(url, headers=headers, timeout=15)
		if resp.status_code in (200, 201):
			data = resp.json()
			properties = data.get("data", [])
			frappe.db.set_single_value("OTA Settings", {
				"connection_status": "Connected",
				"last_connected_at": now_datetime(),
				"last_error": None,
				"last_error_at": None
			})
			frappe.db.commit()
			return {
				"status": "success",
				"message": _("Connected successfully! Found {0} properties.").format(len(properties)),
				"properties": [{"id": p.get("id"), "title": p.get("attributes", {}).get("title", "")} for p in properties[:10]]
			}
		elif resp.status_code == 401:
			log_ota_error("Authentication failed. Check API Key.")
			frappe.throw(_("Authentication failed. Please check your API Key."))
		else:
			log_ota_error(f"HTTP {resp.status_code}: {resp.text[:300]}")
			frappe.throw(_("Connection returned HTTP {0}").format(resp.status_code))
	except requests.exceptions.Timeout:
		log_ota_error("Connection timed out.")
		frappe.throw(_("Connection timed out. Please check your API URL."))
	except requests.exceptions.ConnectionError:
		log_ota_error("Could not connect to API server.")
		frappe.throw(_("Could not connect to server. Check your API Base URL and internet connection."))


@frappe.whitelist()
def fetch_room_types_from_ota():
	"""
	Fetches room types from connected OTA / Channex property and creates
	Hotel Room Type and Hotel Room records in ERPNext if they don't already exist.
	"""
	settings = frappe.get_single("OTA Settings")
	if not settings.property_id:
		frappe.throw(_("Please select a Property in OTA Settings first."))

	headers = get_api_headers()
	url = get_api_url("room_types")
	params = {"filter[property_id]": settings.property_id}

	hotel_settings = frappe.get_single("Hotel Settings")
	default_item = hotel_settings.default_room_item
	if not default_item:
		default_item = "HOTEL-ROOM-NIGHT"
		if not frappe.db.exists("Item", default_item):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": default_item,
				"item_name": "Room Night",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups",
				"is_stock_item": 0,
				"stock_uom": "Nos",
			}).insert(ignore_permissions=True)
		hotel_settings.default_room_item = default_item
		hotel_settings.save(ignore_permissions=True)

	try:
		resp = requests.get(url, headers=headers, params=params, timeout=15)
		if resp.status_code not in (200, 201):
			frappe.throw(_("Failed to fetch room types: HTTP {0} - {1}").format(resp.status_code, resp.text[:200]))

		data = resp.json().get("data", [])
		if not data:
			return {
				"status": "info",
				"message": _("No room types found for this property in OTA. You can click 'Create sample rooms' on Front Desk Console instead.")
			}

		created_types = []
		created_rooms = []

		for idx, item in enumerate(data):
			attrs = item.get("attributes") or {}
			title = (attrs.get("title") or f"Room Type {idx+1}").strip()
			occupancy = int(attrs.get("default_occupancy") or 2)
			count_of_rooms = int(attrs.get("count_of_rooms") or 1)

			# Create Hotel Room Type if not exists
			if not frappe.db.exists("Hotel Room Type", title):
				doc = frappe.get_doc({
					"doctype": "Hotel Room Type",
					"room_type_name": title,
					"max_adults": occupancy,
					"item": default_item,
					"default_rate": float(attrs.get("default_rate") or 2500.0)
				})
				doc.insert(ignore_permissions=True)
				created_types.append(title)

			# Create physical rooms if needed
			base_num = (idx + 1) * 100
			for r_idx in range(1, count_of_rooms + 1):
				room_num = str(base_num + r_idx)
				if not frappe.db.exists("Hotel Room", room_num):
					room_doc = frappe.get_doc({
						"doctype": "Hotel Room",
						"room_number": room_num,
						"room_type": title,
						"floor": str(idx + 1),
						"status": "Available",
						"is_enabled": 1
					})
					room_doc.insert(ignore_permissions=True)
					created_rooms.append(room_num)

		frappe.db.commit()
		return {
			"status": "success",
			"message": _("Synced {0} Room Types and created {1} Rooms.").format(len(data), len(created_rooms)),
			"types_count": len(data),
			"rooms_count": len(created_rooms)
		}
	except Exception as e:
		log_ota_error(str(e))
		frappe.throw(_("Error fetching room types: {0}").format(str(e)))
