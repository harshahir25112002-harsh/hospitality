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
	Fetches room types from connected OTA / Channex property and synchronizes
	Hotel Room Type and Hotel Room records in ERPNext to match Channex exactly.
	Removes extra unused rooms if the room count was reduced in Channex.
	"""
	settings = frappe.get_single("OTA Settings")
	if not settings.property_id:
		frappe.throw(_("Please select a Property in OTA Settings first."))

	headers = get_api_headers()
	url = get_api_url("room_types")
	params = {"filter[property_id]": settings.property_id}

	from hospitality_core.utils import ensure_default_room_item
	default_item = ensure_default_room_item()

	try:
		resp = requests.get(url, headers=headers, params=params, timeout=15)
		if resp.status_code not in (200, 201):
			frappe.throw(_("Failed to fetch room types: HTTP {0} - {1}").format(resp.status_code, resp.text[:200]))

		data = resp.json().get("data", [])
		if not data:
			return {
				"status": "info",
				"message": _("No room types found for this property in OTA.")
			}

				# Cache mapping of Channex room_type_id -> human title
		try:
			channex_map = {}
			for item in data:
				r_id = item.get("id")
				attrs = item.get("attributes") or {}
				t = (attrs.get("title") or "").strip()
				if r_id and t:
					channex_map[r_id] = t
			if channex_map:
				frappe.cache().set_value("channex_room_type_map", channex_map, expires_in_sec=86400)
		except Exception:
			pass

		created_types = []
		created_rooms = []
		deleted_rooms = []

		for idx, item in enumerate(data):
			attrs = item.get("attributes") or {}
			title = (attrs.get("title") or f"Room Type {idx+1}").strip()
			count_of_rooms = int(attrs.get("count_of_rooms") or 1)

			occ_adults = int(
				attrs.get("occ_adults")
				or attrs.get("adults")
				or attrs.get("capacity")
				or attrs.get("max_occupancy")
				or (4 if "family" in title.lower() or "suite" in title.lower() else (2 if "double" in title.lower() or "twin" in title.lower() or "deluxe" in title.lower() else 1))
			)
			occ_children = int(attrs.get("occ_children") or attrs.get("children") or (2 if "family" in title.lower() else 1))
			max_occ = int(attrs.get("max_occupancy") or (occ_adults + occ_children))

			# Create or update Hotel Room Type
			if not frappe.db.exists("Hotel Room Type", title):
				doc = frappe.get_doc({
					"doctype": "Hotel Room Type",
					"room_type_name": title,
					"max_adults": occ_adults,
					"max_children": occ_children,
					"max_occupancy": max_occ,
					"item": default_item,
					"default_rate": float(attrs.get("default_rate") or 2500.0)
				})
				doc.insert(ignore_permissions=True)
				created_types.append(title)
			else:
				frappe.db.set_value("Hotel Room Type", title, {
					"max_adults": occ_adults,
					"max_children": occ_children,
					"max_occupancy": max_occ
				})

			# Check existing rooms for this room type
			existing_rooms = frappe.get_all(
				"Hotel Room",
				filters={"room_type": title},
				fields=["name", "room_number", "current_reservation"],
				order_by="room_number asc, name asc"
			)

			current_count = len(existing_rooms)
			base_num = (idx + 1) * 100

			# If fewer rooms exist than count_of_rooms, create the missing ones
			if current_count < count_of_rooms:
				for r_idx in range(current_count + 1, count_of_rooms + 1):
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

			# If MORE rooms exist than count_of_rooms, safely delete extra unreserved rooms
			elif current_count > count_of_rooms:
				surplus = existing_rooms[count_of_rooms:]
				for r in surplus:
					has_res = r.current_reservation or frappe.db.exists(
						"Hotel Reservation",
						{"room": r.name, "status": ["in", ["Reserved", "Checked In"]]}
					)
					if not has_res:
						try:
							frappe.delete_doc("Hotel Room", r.name, force=True, ignore_permissions=True)
							deleted_rooms.append(r.name)
						except Exception:
							pass

		frappe.db.commit()

		total_now = frappe.db.count("Hotel Room", {"is_enabled": 1})
		msg = _("Successfully synchronized rooms with Channex!<br><br><b>Total Active Rooms in ERPNext: {0}</b>").format(total_now)
		if deleted_rooms:
			msg += _("<br>Cleaned up {0} extra dummy rooms.").format(len(deleted_rooms))

		return {
			"status": "success",
			"message": msg,
			"types_count": len(data),
			"total_rooms": total_now,
			"deleted_count": len(deleted_rooms)
		}
	except Exception as e:
		log_ota_error(str(e))
		frappe.throw(_("Error synchronizing rooms: {0}").format(str(e)))


@frappe.whitelist()
def clean_extra_rooms(keep_per_type=1):
	"""
	Direct utility to clean up any extra dummy rooms in ERPNext,
	keeping only 1 room per room type (or keep_per_type),
	leaving unreserved rooms deleted.
	"""
	keep_per_type = int(keep_per_type or 1)
	room_types = frappe.get_all("Hotel Room Type", fields=["name"])
	deleted = []

	for rt in room_types:
		rooms = frappe.get_all(
			"Hotel Room",
			filters={"room_type": rt.name},
			fields=["name", "current_reservation"],
			order_by="room_number asc, name asc"
		)
		if len(rooms) > keep_per_type:
			surplus = rooms[keep_per_type:]
			for r in surplus:
				has_res = r.current_reservation or frappe.db.exists(
					"Hotel Reservation",
					{"room": r.name, "status": ["in", ["Reserved", "Checked In"]]}
				)
				if not has_res:
					try:
						frappe.delete_doc("Hotel Room", r.name, force=True, ignore_permissions=True)
						deleted.append(r.name)
					except Exception:
						pass

	frappe.db.commit()
	total_left = frappe.db.count("Hotel Room", {"is_enabled": 1})
	return {
		"status": "success",
		"deleted_count": len(deleted),
		"deleted_rooms": deleted,
		"total_rooms_remaining": total_left,
		"message": f"Deleted {len(deleted)} extra rooms. Total rooms remaining: {total_left}"
	}