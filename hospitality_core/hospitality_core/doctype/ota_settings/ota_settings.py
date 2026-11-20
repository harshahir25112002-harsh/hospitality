import requests
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class OTASettings(Document):

	def validate(self):
		if self.enabled and not self.api_base_url:
			frappe.throw(_("API Base URL is required."))
		if self.api_base_url:
			self.api_base_url = self.api_base_url.strip().rstrip("/")
		if not self.feed_endpoint:
			self.feed_endpoint = "booking_revisions/feed"
		if not self.pull_interval_minutes:
			self.pull_interval_minutes = 15


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
