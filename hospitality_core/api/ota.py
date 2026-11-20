import json
import requests
import frappe
from frappe import _
from frappe.utils import (
	cint,
	date_diff,
	flt,
	now_datetime,
)

from hospitality_core.hospitality_core.doctype.ota_settings.ota_settings import (
	get_api_headers,
	get_api_url,
	get_ota_settings,
	log_ota_error,
)


# ---------------------------------------------------------------- Webhook Receiver (Optional)
@frappe.whitelist(allow_guest=True, methods=["POST", "GET"])
def webhook():
	"""
	Optional receiver endpoint if an OTA or channel manager pushes booking webhooks.
	Saves incoming booking directly into OTA Reservation.
	"""
	if frappe.request.method == "GET":
		return {"status": "ok", "message": "OTA receiver endpoint active"}

	try:
		raw_data = frappe.request.get_data(as_text=True)
		payload = json.loads(raw_data) if raw_data else (frappe.form_dict or {})
	except Exception as e:
		frappe.log_error(title="OTA Webhook: Invalid JSON", message=str(e))
		return {"status": "error", "message": "Invalid JSON"}

	try:
		data = payload.get("payload") or payload.get("data") or payload
		revision_id = data.get("revision_id") or data.get("id")
		booking_id = data.get("booking_id")

		booking_data = data
		if not data.get("rooms") and (revision_id or booking_id):
			fetched = fetch_booking_details(revision_id or booking_id)
			if fetched:
				booking_data = fetched

		save_ota_reservation(booking_data, raw_data=raw_data, revision_id=revision_id)
	except Exception as e:
		frappe.log_error(title="OTA Webhook Error", message=frappe.get_traceback())

	return {"status": "success", "message": "Received"}


def fetch_booking_details(booking_or_rev_id):
	"""Fetches full details from API using the configured API Base URL."""
	try:
		headers = get_api_headers()
		url = get_api_url(f"booking_revisions/{booking_or_rev_id}")
		resp = requests.get(url, headers=headers, timeout=15)
		if resp.status_code == 200:
			res = resp.json()
			return res.get("data", {}).get("attributes") or res.get("data")
		# Fallback to bookings endpoint
		url_booking = get_api_url(f"bookings/{booking_or_rev_id}")
		resp_b = requests.get(url_booking, headers=headers, timeout=15)
		if resp_b.status_code == 200:
			res = resp_b.json()
			return res.get("data", {}).get("attributes") or res.get("data")
	except Exception:
		pass
	return None


# ---------------------------------------------------------------- Core 15-Minute Pull Feed
@frappe.whitelist()
def pull_booking_revisions():
	"""
	Pulls latest OTA bookings from the configured server.
	Checks both the live booking revisions feed and the bookings collection.
	Saves directly into OTA Reservation.
	"""
	settings = get_ota_settings()
	if not settings.enabled:
		return {"status": "skipped", "message": "OTA Sync is disabled"}

	headers = get_api_headers()
	processed_count = 0
	total_received = 0

	# 1. First, check the live revisions feed
	endpoint = (settings.feed_endpoint or "booking_revisions/feed").strip().lstrip("/")
	feed_url = get_api_url(endpoint)
	try:
		resp = requests.get(feed_url, headers=headers, timeout=20)
		if resp.status_code == 200:
			feed_data = resp.json().get("data", [])
			total_received += len(feed_data)
			for item in feed_data:
				rev_id = item.get("id")
				attrs = item.get("attributes") or item
				attrs["revision_id"] = rev_id
				res_name = save_ota_reservation(attrs, revision_id=rev_id)
				if res_name:
					processed_count += 1
				if settings.auto_acknowledge and rev_id:
					acknowledge_revision(rev_id)
	except Exception as e:
		frappe.log_error(title="OTA Feed Error", message=str(e))

	# 2. Also check the bookings endpoint to ensure all existing bookings (like those created in demo/portal) are fetched
	try:
		bookings_url = get_api_url("bookings")
		params = {}
		if settings.property_id:
			params["filter[property_id]"] = settings.property_id

		resp_b = requests.get(bookings_url, headers=headers, params=params, timeout=20)
		if resp_b.status_code == 200:
			bookings_data = resp_b.json().get("data", [])
			if not bookings_data and settings.property_id:
				resp_b2 = requests.get(bookings_url, headers=headers, timeout=20)
				if resp_b2.status_code == 200:
					bookings_data = resp_b2.json().get("data", [])

			total_received += len(bookings_data)
			for item in bookings_data:
				b_id = item.get("id")
				attrs = item.get("attributes") or item
				attrs["booking_id"] = b_id
				res_name = save_ota_reservation(attrs, revision_id=b_id)
				if res_name:
					processed_count += 1
	except Exception as e:
		frappe.log_error(title="OTA Bookings Error", message=str(e))

	# Update last pull timestamp & counter
	frappe.db.set_single_value("OTA Settings", {
		"last_pull_at": now_datetime(),
		"connection_status": "Connected"
	})
	try:
		frappe.db.sql(
			"UPDATE `tabSingles` SET value = CAST(value AS UNSIGNED) + %s WHERE doctype = 'OTA Settings' AND field = 'total_bookings_received'",
			(processed_count,)
		)
	except Exception:
		pass
	frappe.db.commit()

	return {"status": "success", "processed": processed_count, "total_received": total_received}


# ---------------------------------------------------------------- Save OTA Reservation
def save_ota_reservation(data, raw_data="", revision_id=None):
	"""
	Creates or updates an OTA Reservation directly with incoming booking data.
	"""
	if not data:
		return None

	ota_booking_id = (
		data.get("unique_id")
		or data.get("ota_reservation_code")
		or data.get("booking_id")
		or data.get("id")
		or revision_id
	)
	if not ota_booking_id:
		return None

	channel_name = (
		data.get("ota_name")
		or data.get("channel")
		or data.get("source")
		or "OTA"
	)
	raw_status = (data.get("status") or "new").lower()
	status_map = {
		"new": "New",
		"confirmed": "Confirmed",
		"modified": "Modified",
		"cancelled": "Cancelled",
		"canceled": "Cancelled"
	}
	status = status_map.get(raw_status, "New")

	# Guest details
	customer_data = data.get("customer") or {}
	first_name = customer_data.get("name") or customer_data.get("first_name") or ""
	last_name = customer_data.get("surname") or customer_data.get("last_name") or ""
	guest_name = f"{first_name} {last_name}".strip() or data.get("guest_name") or "OTA Guest"
	email = customer_data.get("mail") or customer_data.get("email") or data.get("email") or ""
	phone = customer_data.get("phone") or customer_data.get("mobile") or data.get("phone") or ""

	# Dates & Occupancy
	check_in = data.get("arrival_date") or data.get("check_in")
	check_out = data.get("departure_date") or data.get("check_out")

	rooms = data.get("rooms") or []
	first_room = rooms[0] if rooms else {}
	room_type = (
		first_room.get("room_type_name")
		or first_room.get("room_type_title")
		or first_room.get("room_type_id")
		or data.get("room_type_name")
		or ""
	)
	rate_plan = (
		first_room.get("rate_plan_name")
		or first_room.get("rate_plan_title")
		or first_room.get("rate_plan_id")
		or data.get("rate_plan_name")
		or ""
	)

	occupancy = first_room.get("occupancy") or {}
	adults = cint(occupancy.get("adults") or data.get("adults") or 1)
	children = cint(occupancy.get("children") or data.get("children") or 0)

	total_amount = flt(data.get("amount") or data.get("total_price") or 0.0)
	currency = data.get("currency") or "INR"
	commission = flt(data.get("ota_commission") or data.get("commission") or 0.0)
	payment_status = data.get("payment_status") or ""
	payment_collect = data.get("payment_collect") or data.get("collect_type") or ""

	# Check if this OTA booking already exists
	existing_name = frappe.db.get_value("OTA Reservation", {"ota_booking_id": str(ota_booking_id)}, "name")
	if existing_name:
		doc = frappe.get_doc("OTA Reservation", existing_name)
	else:
		doc = frappe.new_doc("OTA Reservation")
		doc.ota_booking_id = str(ota_booking_id)

	doc.channel_name = channel_name
	doc.status = status
	doc.guest_name = guest_name
	doc.guest_email = email
	doc.guest_phone = phone
	doc.check_in_date = check_in
	doc.check_out_date = check_out
	if check_in and check_out:
		doc.nights = max(date_diff(check_out, check_in), 1)
	doc.adults = adults
	doc.children = children
	doc.room_type_name = room_type
	doc.rate_plan_name = rate_plan
	doc.total_amount = total_amount
	doc.currency = currency
	doc.commission = commission
	doc.payment_status = payment_status
	doc.payment_collect = payment_collect
	doc.received_at = now_datetime()
	doc.raw_payload = raw_data or json.dumps(data, indent=2, default=str)

	doc.flags.ignore_permissions = True
	doc.save()
	frappe.db.commit()

	return doc.name


def acknowledge_revision(revision_id):
	"""Acknowledges received booking revision to server."""
	try:
		headers = get_api_headers()
		url = get_api_url(f"booking_revisions/{revision_id}/ack")
		resp = requests.post(url, headers=headers, json={}, timeout=15)
		return resp.status_code in (200, 204)
	except Exception:
		return False
