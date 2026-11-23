import json
import requests
import frappe
from frappe import _
from frappe.utils import (
	add_days,
	cint,
	date_diff,
	flt,
	getdate,
	now_datetime,
	nowdate,
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



def get_ota_room_type_map():
	"""Fetches mapping of Channex room_type_id (UUID) -> human title (e.g. Demo Family)."""
	room_map = frappe.cache().get_value("channex_room_type_map") or {}
	if room_map:
		return room_map

	try:
		settings = get_ota_settings()
		if settings.property_id:
			headers = get_api_headers()
			url = get_api_url("room_types")
			params = {"filter[property_id]": settings.property_id}
			resp = requests.get(url, headers=headers, params=params, timeout=12)
			if resp.status_code == 200:
				for item in resp.json().get("data", []):
					r_id = item.get("id")
					title = (item.get("attributes", {}).get("title") or "").strip()
					if r_id and title:
						room_map[r_id] = title
				if room_map:
					frappe.cache().set_value("channex_room_type_map", room_map, expires_in_sec=86400)
	except Exception:
		pass

	# Fallback: check Hotel Room Type records
	if not room_map:
		for rt in frappe.get_all("Hotel Room Type", fields=["name", "room_type_name"]):
			title = rt.room_type_name or rt.name
			# Store title as its own key
			room_map[title] = title
	return room_map


def get_ota_rate_plan_map():
	"""Fetches mapping of Channex rate_plan_id (UUID) -> human title (e.g. Standard Rate)."""
	rate_map = frappe.cache().get_value("channex_rate_plan_map") or {}
	if rate_map:
		return rate_map

	try:
		settings = get_ota_settings()
		if settings.property_id:
			headers = get_api_headers()
			url = get_api_url("rate_plans")
			params = {"filter[property_id]": settings.property_id}
			resp = requests.get(url, headers=headers, params=params, timeout=12)
			if resp.status_code == 200:
				for item in resp.json().get("data", []):
					rp_id = item.get("id")
					title = (item.get("attributes", {}).get("title") or "").strip()
					if rp_id and title:
						rate_map[rp_id] = title
				if rate_map:
					frappe.cache().set_value("channex_rate_plan_map", rate_map, expires_in_sec=86400)
	except Exception:
		pass
	return rate_map



def fix_hotel_room_type_capacities():
	"""Ensures room types have realistic adult/child capacities based on their names."""
	try:
		for rt in frappe.get_all("Hotel Room Type", fields=["name", "room_type_name", "max_adults", "max_occupancy"]):
			name = (rt.room_type_name or rt.name).strip()
			lower = name.lower()
			target_adults = 4 if ("family" in lower or "suite" in lower) else (2 if ("double" in lower or "twin" in lower or "deluxe" in lower) else 1)
			if cint(rt.max_adults) < target_adults:
				frappe.db.set_value("Hotel Room Type", rt.name, {
					"max_adults": target_adults,
					"max_occupancy": max(target_adults + 2, cint(rt.max_occupancy))
				})
		frappe.db.commit()
	except Exception:
		pass


def fix_existing_ota_reservations(room_type_map=None, rate_plan_map=None):
	"""Resolves any existing raw UUIDs in OTA Reservation records to human titles."""
	try:
		if not room_type_map:
			room_type_map = get_ota_room_type_map()
		if not rate_plan_map:
			rate_plan_map = get_ota_rate_plan_map()

		records = frappe.get_all("OTA Reservation", fields=["name", "room_type_name", "rate_plan_name", "raw_payload"])
		for rec in records:
			updates = {}
			rt = (rec.room_type_name or "").strip()
			if len(rt) == 36 and rt in room_type_map:
				updates["room_type_name"] = room_type_map[rt]
			elif len(rt) == 36 or not rt:
				# Try from raw_payload or fallback to known types
				matched = False
				for uuid, title in room_type_map.items():
					if uuid in (rec.raw_payload or ""):
						updates["room_type_name"] = title
						matched = True
						break
				if not matched:
					# Match any room type mentioned in payload
					for title in ["Demo Family", "Demo Double", "Demo Single", "Demo Signle"]:
						if title.lower() in (rec.raw_payload or "").lower():
							updates["room_type_name"] = title
							matched = True
							break
				if not matched and room_type_map:
					# Pick first title from map
					first_val = list(room_type_map.values())[0]
					if len(first_val) != 36:
						updates["room_type_name"] = first_val

			rp = (rec.rate_plan_name or "").strip()
			if len(rp) == 36 and rp in rate_plan_map:
				updates["rate_plan_name"] = rate_plan_map[rp]
			elif len(rp) == 36 or not rp:
				updates["rate_plan_name"] = "Standard Rate"

			if updates:
				frappe.db.set_value("OTA Reservation", rec.name, updates)
		frappe.db.commit()
	except Exception:
		pass


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

	# 0. Load mappings
	room_type_map = get_ota_room_type_map()
	rate_plan_map = get_ota_rate_plan_map()

	# Automatically sync room types and rooms from Channex if property configured
	try:
		if settings.property_id:
			from hospitality_core.hospitality_core.doctype.ota_settings.ota_settings import fetch_room_types_from_ota
			fetch_room_types_from_ota()
			room_type_map = get_ota_room_type_map()
			rate_plan_map = get_ota_rate_plan_map()
	except Exception as e:
		frappe.log_error(title="OTA Auto-Sync Rooms Error", message=str(e))

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
				res_name = save_ota_reservation(attrs, revision_id=rev_id, room_type_map=room_type_map, rate_plan_map=rate_plan_map)
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
				res_name = save_ota_reservation(attrs, revision_id=b_id, room_type_map=room_type_map, rate_plan_map=rate_plan_map)
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

	return {
		"status": "success",
		"processed": processed_count,
		"total_received": total_received,
		"property_id": settings.property_id or "None",
		"message": _("Fetched {0} booking(s) from Channex.").format(processed_count)
	}


# ---------------------------------------------------------------- Save OTA Reservation
def sanitize_email(val):
	if not val:
		return ""
	val = str(val).strip()
	if val in ("***", "N/A", "none", "null", "-", "undefined") or val.startswith("*"):
		return ""
	if "@" in val and "." in val:
		return val
	return ""


def save_ota_reservation(data, raw_data="", revision_id=None, room_type_map=None, rate_plan_map=None):
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
	email = sanitize_email(customer_data.get("mail") or customer_data.get("email") or data.get("email") or "")
	raw_phone = customer_data.get("phone") or customer_data.get("mobile") or data.get("phone") or ""
	phone = "" if str(raw_phone).strip() in ("***", "N/A", "none", "null", "-") else str(raw_phone).strip()

	# Dates & Occupancy
	check_in = data.get("arrival_date") or data.get("check_in")
	check_out = data.get("departure_date") or data.get("check_out")

	if not room_type_map:
		room_type_map = get_ota_room_type_map()
	if not rate_plan_map:
		rate_plan_map = get_ota_rate_plan_map()

	rooms = data.get("rooms") or []
	first_room = rooms[0] if rooms else {}
	raw_rt_id = str(first_room.get("room_type_id") or "").strip()
	raw_rt_title = str(first_room.get("room_type_title") or first_room.get("room_type_name") or data.get("room_type_name") or "").strip()

	if raw_rt_title and len(raw_rt_title) != 36:
		room_type = raw_rt_title
	elif raw_rt_id in room_type_map:
		room_type = room_type_map[raw_rt_id]
	elif raw_rt_title in room_type_map:
		room_type = room_type_map[raw_rt_title]
	else:
		room_type = raw_rt_title or raw_rt_id or "Standard"

	raw_rp_id = str(first_room.get("rate_plan_id") or "").strip()
	raw_rp_title = str(first_room.get("rate_plan_title") or first_room.get("rate_plan_name") or data.get("rate_plan_name") or "").strip()

	if raw_rp_title and len(raw_rp_title) != 36:
		rate_plan = raw_rp_title
	elif raw_rp_id in rate_plan_map:
		rate_plan = rate_plan_map[raw_rp_id]
	else:
		rate_plan = "Standard Rate"

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

	# If this is a cancellation, automatically cancel any existing Hotel Reservation
	if status == "Cancelled" and doc.hotel_reservation:
		try:
			res_doc = frappe.get_doc("Hotel Reservation", doc.hotel_reservation)
			if res_doc.status != "Cancelled":
				res_doc.status = "Cancelled"
				res_doc.flags.ignore_permissions = True
				res_doc.save()
		except Exception:
			pass

	frappe.db.commit()

	# Immediately trigger real-time availability update back to Channex
	if doc.room_type_name and doc.check_in_date and doc.check_out_date:
		try:
			push_room_type_availability_to_ota(doc.room_type_name, doc.check_in_date, doc.check_out_date)
		except Exception:
			pass

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


# ---------------------------------------------------------------- 2-Way OTA Availability & Restrictions Push
@frappe.whitelist()
def sync_push_inventory(days=30):
	"""
	Pushes real-time room availability and stop-sell flags from ERPNext to Channex.
	Synchronizes all active room types for the next `days` (default: 30 days).
	Eliminates overbooking by closing OTA channels when rooms are sold locally.
	"""
	settings = get_ota_settings()
	if not settings.enabled or not settings.property_id:
		return {"status": "skipped", "message": "OTA synchronization is disabled or property is not set"}

	days = min(cint(days) or 30, 60)
	room_types = frappe.get_all("Hotel Room Type", fields=["name", "room_type_name"])
	if not room_types:
		return {"status": "skipped", "message": "No Hotel Room Types found"}

	rt_map = get_ota_room_type_map()
	# Reverse map: human room type title -> Channex room_type_id (UUID)
	title_to_uuid = {}
	for uuid, title in rt_map.items():
		title_to_uuid[title.lower()] = uuid

	headers = get_api_headers()
	url = get_api_url("restrictions")

	start_d = getdate(nowdate())
	total_entries = 0
	pushed_types = []

	from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import get_room_type_availability

	values = []
	for rt in room_types:
		rt_title = (rt.room_type_name or rt.name).strip()
		channex_uuid = title_to_uuid.get(rt_title.lower()) or title_to_uuid.get(rt.name.lower())
		if not channex_uuid:
			continue

		from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import get_room_rate, get_room_type_availability
		pushed_types.append(rt_title)
		for i in range(days):
			d = add_days(start_d, i)
			next_d = add_days(d, 1)
			avail_info = get_room_type_availability(rt.name, d, next_d)
			free_count = max(cint(avail_info.get("available", 0)), 0)
			is_stop_sell = (free_count <= 0)
			daily_rate = get_room_rate(rt.name, d)

			entry = {
				"property_id": settings.property_id,
				"room_type_id": channex_uuid,
				"date_from": str(d),
				"date_to": str(d),
				"availability": free_count,
				"stop_sell": is_stop_sell
			}
			if daily_rate:
				entry["rate"] = flt(daily_rate, 2)
			values.append(entry)
			total_entries += 1

	if not values:
		return {
			"status": "info",
			"message": _("No matching Channex room types found to push. Check OTA Settings.")
		}

	# Send in batches of 100 to Channex
	success_count = 0
	batch_size = 100
	for i in range(0, len(values), batch_size):
		batch = values[i:i + batch_size]
		try:
			resp = requests.post(url, headers=headers, json={"values": batch}, timeout=25)
			if resp.status_code in (200, 201, 204):
				success_count += len(batch)
			else:
				log_ota_error(f"Push Inventory failed: HTTP {resp.status_code} - {resp.text[:300]}")
		except Exception as e:
			log_ota_error(f"Push Inventory error: {str(e)}")

	return {
		"status": "success",
		"message": _("Pushed real-time inventory to Channex for {0} room type(s) across {1} days ({2} updates sent).").format(
			len(pushed_types), days, success_count
		),
		"room_types": pushed_types,
		"updates_sent": success_count
	}


def push_room_type_availability_to_ota(room_type, from_date, to_date):
	"""
	Automatically updates Channex availability for a specific room type and date range
	whenever a reservation is created, checked in, checked out, or cancelled in ERPNext.
	"""
	try:
		settings = get_ota_settings()
		if not settings.enabled or not settings.property_id:
			return

		rt_map = get_ota_room_type_map()
		title_to_uuid = {t.lower(): u for u, t in rt_map.items()}

		channex_uuid = title_to_uuid.get(room_type.lower())
		if not channex_uuid:
			return

		start_d = getdate(from_date)
		end_d = getdate(to_date)
		num_days = max(date_diff(end_d, start_d), 1)

		from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import get_room_rate, get_room_type_availability
		values = []
		for i in range(num_days):
			d = add_days(start_d, i)
			avail = get_room_type_availability(room_type, d, add_days(d, 1))
			free_count = max(cint(avail.get("available", 0)), 0)
			daily_rate = get_room_rate(room_type, d)
			entry = {
				"property_id": settings.property_id,
				"room_type_id": channex_uuid,
				"date_from": str(d),
				"date_to": str(d),
				"availability": free_count,
				"stop_sell": (free_count <= 0)
			}
			if daily_rate:
				entry["rate"] = flt(daily_rate, 2)
			values.append(entry)

		if values:
			headers = get_api_headers()
			url = get_api_url("restrictions")
			requests.post(url, headers=headers, json={"values": values}, timeout=15)
	except Exception:
		pass


def on_hotel_room_change(doc, method=None):
	"""
	Automatically updates Channex OTA inventory whenever a Hotel Room
	is added, updated, enabled/disabled, or deleted in ERPNext.
	"""
	try:
		if not doc.room_type:
			return
		push_room_type_availability_to_ota(doc.room_type, nowdate(), add_days(nowdate(), 30))
	except Exception:
		pass


def on_reservation_change(doc, method=None):
	"""
	Automatically updates Channex OTA inventory whenever a Hotel Reservation
	is created, updated, checked-in, or cancelled.
	"""
	try:
		if not doc.room_type or not doc.check_in_date or not doc.check_out_date:
			return
		push_room_type_availability_to_ota(doc.room_type, doc.check_in_date, doc.check_out_date)
	except Exception:
		pass


def on_rate_plan_change(doc, method=None):
	"""
	Automatically updates Channex OTA rates whenever a Room Rate Plan
	(such as a Festival, Peak Season, or Weekend rate) is created or modified.
	"""
	try:
		if not doc.room_type or not doc.valid_from or not doc.valid_to:
			return
		push_room_type_availability_to_ota(doc.room_type, doc.valid_from, doc.valid_to)
	except Exception:
		pass

