import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


STAGING_URL = "https://staging.channex.io/api/v1"
PRODUCTION_URL = "https://app.channex.io/api/v1"


class OTASettings(Document):

	def validate(self):
		self.set_api_url()
		self.set_webhook_url()
		self.validate_pull_interval()
		if self.enabled and not self.api_key:
			frappe.throw(_("Channex API Key is required when OTA Integration is enabled."))

	def set_api_url(self):
		self.api_base_url = PRODUCTION_URL if self.environment == "Production" else STAGING_URL

	def set_webhook_url(self):
		site_url = frappe.utils.get_url()
		self.webhook_url = f"{site_url}/api/method/hospitality_core.api.ota.webhook"

	def validate_pull_interval(self):
		if self.pull_interval_minutes and int(self.pull_interval_minutes) < 5:
			frappe.throw(_("Pull interval must be at least 5 minutes."))
		if not self.pull_interval_minutes:
			self.pull_interval_minutes = 15


def get_ota_settings():
	"""Returns cached OTA Settings single doc."""
	return frappe.get_cached_doc("OTA Settings")


def get_api_headers():
	"""Returns headers for Channex API calls."""
	settings = get_ota_settings()
	if not settings.enabled:
		frappe.throw(_("OTA Integration is not enabled. Enable it in OTA Settings."))
	api_key = settings.get_password("api_key")
	if not api_key:
		frappe.throw(_("Channex API Key is not configured in OTA Settings."))
	return {
		"Content-Type": "application/json",
		"user-api-key": api_key
	}


def get_api_url(endpoint=""):
	"""Returns full Channex API URL for an endpoint."""
	settings = get_ota_settings()
	base = settings.api_base_url or STAGING_URL
	return f"{base}/{endpoint.lstrip('/')}" if endpoint else base


def get_room_type_channex_id(room_type):
	"""Looks up the Channex Room Type ID for a local Hotel Room Type."""
	settings = get_ota_settings()
	for row in settings.room_type_map:
		if row.room_type == room_type:
			return row.channex_room_type_id
	return None


def get_local_room_type(channex_room_type_id):
	"""Reverse lookup: Channex Room Type ID → local Hotel Room Type."""
	settings = get_ota_settings()
	for row in settings.room_type_map:
		if row.channex_room_type_id == channex_room_type_id:
			return row.room_type
	return None


def get_rate_plan_channex_id(rate_plan):
	"""Looks up the Channex Rate Plan ID for a local Room Rate Plan."""
	settings = get_ota_settings()
	for row in settings.rate_plan_map:
		if row.rate_plan == rate_plan:
			return row.channex_rate_plan_id
	return None


def get_local_rate_plan(channex_rate_plan_id):
	"""Reverse lookup: Channex Rate Plan ID → local Room Rate Plan."""
	settings = get_ota_settings()
	for row in settings.rate_plan_map:
		if row.channex_rate_plan_id == channex_rate_plan_id:
			return row.rate_plan
	return None


def log_ota_error(error_message):
	"""Saves the last error to OTA Settings for quick visibility."""
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
	"""Tests the Channex API connection and returns the result."""
	settings = frappe.get_single("OTA Settings")
	if not settings.api_key:
		frappe.throw(_("Please enter the Channex API Key first."))

	import requests
	headers = get_api_headers()
	url = get_api_url("properties")

	try:
		resp = requests.get(url, headers=headers, timeout=15)
		if resp.status_code == 200:
			data = resp.json()
			properties = data.get("data", [])
			frappe.db.set_single_value("OTA Settings", {
				"connection_status": "Connected",
				"last_connected_at": now_datetime(),
				"last_error": None,
				"last_error_at": None
			})
			return {
				"status": "success",
				"message": _("Connected successfully! Found {0} properties.").format(len(properties)),
				"properties": [{"id": p["id"], "title": p["attributes"].get("title", "")} for p in properties[:10]]
			}
		elif resp.status_code == 401:
			log_ota_error("Authentication failed. Check API Key.")
			frappe.throw(_("Authentication failed. Please check your Channex API Key."))
		else:
			log_ota_error(f"HTTP {resp.status_code}: {resp.text[:300]}")
			frappe.throw(_("Connection failed: HTTP {0}").format(resp.status_code))
	except requests.exceptions.Timeout:
		log_ota_error("Connection timed out.")
		frappe.throw(_("Connection timed out. Please try again."))
	except requests.exceptions.ConnectionError:
		log_ota_error("Could not connect to Channex.")
		frappe.throw(_("Could not connect to Channex. Check your internet connection."))

