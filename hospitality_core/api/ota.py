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

from hospitality_core.constants import ReservationStatus
from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import (
	get_room_type_availability,
)
from hospitality_core.hospitality_core.doctype.ota_settings.ota_settings import (
	get_api_headers,
	get_api_url,
	get_local_rate_plan,
	get_local_room_type,
	get_ota_settings,
	get_rate_plan_channex_id,
	get_room_type_channex_id,
	log_ota_error,
)
from hospitality_core.utils import get_company, get_settings


# ---------------------------------------------------------------- Webhook Endpoint
@frappe.whitelist(allow_guest=True, methods=["POST", "GET"])
def webhook():
	"""
	Receives real-time booking push notifications from Channex.
	Per Channex requirement, always responds with HTTP 200 OK.
	"""
	if frappe.request.method == "GET":
		return {"status": "ok", "message": "OTA Webhook endpoint active"}

	try:
		raw_data = frappe.request.get_data(as_text=True)
		payload = json.loads(raw_data) if raw_data else (frappe.form_dict or {})
	except Exception as e:
		frappe.log_error(title="OTA Webhook: Invalid JSON payload", message=str(e))
		return {"status": "error", "message": "Invalid JSON"}

	# Verify secret token if configured
	settings = get_ota_settings()
	configured_secret = settings.get_password("webhook_secret")
	if configured_secret:
		req_secret = (
			frappe.get_request_header("x-channex-secret")
			or frappe.get_request_header("x-webhook-secret")
			or frappe.form_dict.get("secret")
		)
		if req_secret and req_secret != configured_secret:
			frappe.log_error(title="OTA Webhook: Unauthorized", message="Secret mismatch")
			return {"status": "unauthorized", "message": "Invalid secret"}

	try:
		process_webhook_payload(payload, raw_data)
	except Exception as e:
		frappe.log_error(title="OTA Webhook Processing Error", message=frappe.get_traceback())
		log_ota_error(f"Webhook processing error: {str(e)[:300]}")

	# Return HTTP 200 OK always as required by Channex
	return {"status": "success", "message": "Webhook received"}


def process_webhook_payload(payload, raw_data=""):
	"""Extracts event and booking data from Channex webhook payload."""
	event = payload.get("event") or payload.get("type") or "booking"
	data = payload.get("payload") or payload.get("data") or payload

	# If Channex sent a booking revision notification (ID only), fetch full details
	revision_id = data.get("revision_id") or data.get("id")
	booking_id = data.get("booking_id")

	booking_data = data
	if not data.get("rooms") and (revision_id or booking_id):
		fetched = fetch_booking_revision(revision_id or booking_id)
		if fetched:
			booking_data = fetched

	return handle_booking_revision_record(booking_data, raw_data=raw_data, revision_id=revision_id)


def fetch_booking_revision(revision_or_booking_id):
	"""Fetches full booking revision details from Channex API."""
	try:
		headers = get_api_headers()
		url = get_api_url(f"booking_revisions/{revision_or_booking_id}")
		resp = requests.get(url, headers=headers, timeout=15)
		if resp.status_code == 200:
			res = resp.json()
			return res.get("data", {}).get("attributes") or res.get("data")
		# Fallback to bookings endpoint
		url_booking = get_api_url(f"bookings/{revision_or_booking_id}")
		resp_b = requests.get(url_booking, headers=headers, timeout=15)
		if resp_b.status_code == 200:
			res = resp_b.json()
			return res.get("data", {}).get("attributes") or res.get("data")
	except Exception as e:
		frappe.log_error(title="OTA: Failed to fetch revision", message=str(e))
	return None


# ---------------------------------------------------------------- Booking Processor
def handle_booking_revision_record(booking_data, raw_data="", revision_id=None):
	"""
	Parses incoming booking data, saves to OTA Booking Log, creates or updates
	Hotel Reservation, and acknowledges the revision to Channex.
	"""
	if not booking_data:
		return None

	ota_booking_id = (
		booking_data.get("ota_reservation_code")
		or booking_data.get("booking_id")
		or booking_data.get("id")
		or revision_id
	)
	if not ota_booking_id:
		return None

	ota_source = (
		booking_data.get("ota_name")
		or booking_data.get("channel")
		or booking_data.get("source")
		or "OTA"
	)
	ota_status = (booking_data.get("status") or "new").lower()

	# Customer & Guest details
	customer_data = booking_data.get("customer") or {}
	first_name = customer_data.get("name") or customer_data.get("first_name") or ""
	last_name = customer_data.get("surname") or customer_data.get("last_name") or ""
	guest_name = f"{first_name} {last_name}".strip() or booking_data.get("guest_name") or "OTA Guest"
	email = customer_data.get("email") or booking_data.get("email")
	phone = customer_data.get("phone") or customer_data.get("mobile") or booking_data.get("phone")

	# Dates & Occupancy
	check_in = booking_data.get("arrival_date") or booking_data.get("check_in")
	check_out = booking_data.get("departure_date") or booking_data.get("check_out")

	# Room details from rooms array
	rooms = booking_data.get("rooms") or []
	first_room = rooms[0] if rooms else {}
	channex_rt_id = (
		first_room.get("room_type_id")
		or booking_data.get("room_type_id")
	)
	channex_rp_id = (
		first_room.get("rate_plan_id")
		or booking_data.get("rate_plan_id")
	)

	occupancy = first_room.get("occupancy") or {}
	adults = cint(occupancy.get("adults") or booking_data.get("adults") or 1)
	children = cint(occupancy.get("children") or booking_data.get("children") or 0)

	# Pricing
	total_amount = flt(booking_data.get("total_price") or booking_data.get("amount") or 0.0)
	currency = booking_data.get("currency") or "INR"
	commission = flt(booking_data.get("commission") or 0.0)
	payment_status = booking_data.get("payment_status") or ""
	payment_collect = booking_data.get("payment_collect") or booking_data.get("collect_type") or ""

	# Check if this booking ID log already exists
	existing_log_name = frappe.db.get_value("OTA Booking Log", {"ota_booking_id": ota_booking_id}, "name")
	if existing_log_name:
		log = frappe.get_doc("OTA Booking Log", existing_log_name)
	else:
		log = frappe.new_doc("OTA Booking Log")
		log.ota_booking_id = str(ota_booking_id)

	log.ota_source = ota_source
	log.ota_status = ota_status
	log.guest_name = guest_name
	log.guest_email = email
	log.guest_phone = phone
	log.check_in = check_in
	log.check_out = check_out
	log.adults = adults
	log.children = children
	log.channex_room_type_id = channex_rt_id
	log.channex_rate_plan_id = channex_rp_id
	log.total_amount = total_amount
	log.currency = currency
	log.commission = commission
	log.payment_status = payment_status
	log.payment_collect_type = payment_collect
	log.received_at = now_datetime()
	log.raw_payload = raw_data or json.dumps(booking_data, indent=2, default=str)
	log.status = "New"

	# Resolve local room type & rate plan mappings
	log.map_room_type()
	log.map_rate_plan()
	log.save(ignore_permissions=True)
	frappe.db.commit()

	settings = get_ota_settings()

	# Auto create / update reservation
	res_result = None
	if settings.auto_create_reservation:
		try:
			res_result = create_reservation_from_log(log, ota_status=ota_status)
		except Exception as e:
			log.status = "Failed"
			log.error_message = str(e)[:500]
			log.save(ignore_permissions=True)
			frappe.db.commit()
			frappe.log_error(title="OTA: Auto Create Reservation Failed", message=str(e))

	# Acknowledge revision to Channex (mandatory!)
	rev_id_to_ack = revision_id or booking_data.get("revision_id") or booking_data.get("id")
	if settings.auto_acknowledge and rev_id_to_ack:
		ack_success = acknowledge_booking_revision(rev_id_to_ack)
		if ack_success:
			log.acknowledged = 1
			log.acknowledged_at = now_datetime()
			if log.status == "New":
				log.status = "Acknowledged"
			log.save(ignore_permissions=True)
			frappe.db.commit()

	# Update total bookings received counter
	try:
		frappe.db.sql(
			"UPDATE `tabSingles` SET value = CAST(value AS UNSIGNED) + 1 WHERE doctype = 'OTA Settings' AND field = 'total_bookings_received'"
		)
		frappe.db.commit()
	except Exception:
		pass

	return {"log": log.name, "reservation": log.reservation, "status": log.status}


def create_reservation_from_log(log, ota_status="new"):
	"""Creates, modifies, or cancels a Hotel Reservation from an OTA Booking Log."""
	settings = get_ota_settings()
	hotel_settings = get_settings()
	company = hotel_settings.company or get_company()

	# 1. Handle Cancellation
	if ota_status in ("cancelled", "canceled"):
		if log.reservation:
			res = frappe.get_doc("Hotel Reservation", log.reservation)
			if res.status == ReservationStatus.RESERVED:
				from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import (
					cancel_reservation,
				)
				cancel_reservation(res.name)
				log.status = "Cancelled"
				log.processed_at = now_datetime()
				log.save(ignore_permissions=True)
				frappe.db.commit()
				if settings.auto_sync_availability:
					trigger_availability_push(res.room_type)
				return {"status": "cancelled", "reservation": res.name}
		log.status = "Cancelled"
		log.processed_at = now_datetime()
		log.save(ignore_permissions=True)
		frappe.db.commit()
		return {"status": "cancelled"}

	# 2. Match or Create Customer (Guest Profile)
	customer_name = get_or_create_ota_customer(log.guest_name, log.guest_email, log.guest_phone, settings)
	log.customer = customer_name

	# 3. Resolve Room Type
	room_type = log.room_type
	if not room_type and log.channex_room_type_id:
		room_type = get_local_room_type(log.channex_room_type_id)
	if not room_type:
		# Fallback to the first active Hotel Room Type
		first_rt = frappe.db.get_value("Hotel Room Type", {"is_active": 1}, "name")
		if not first_rt:
			frappe.throw(_("No active Hotel Room Type found to assign this OTA booking."))
		room_type = first_rt
	log.room_type = room_type

	# 4. Resolve Rate Plan
	rate_plan = log.rate_plan
	if not rate_plan and log.channex_rate_plan_id:
		rate_plan = get_local_rate_plan(log.channex_rate_plan_id)
	log.rate_plan = rate_plan

	# 5. Handle Modification on existing reservation
	if log.reservation and frappe.db.exists("Hotel Reservation", log.reservation):
		res = frappe.get_doc("Hotel Reservation", log.reservation)
		if res.status == ReservationStatus.RESERVED:
			res.check_in_date = log.check_in
			res.check_out_date = log.check_out
			res.adults = log.adults or 1
			res.children = log.children or 0
			res.room_type = room_type
			res.estimated_total = log.total_amount
			res.balance = log.total_amount
			if res.stays:
				res.stays[0].from_date = log.check_in
				res.stays[0].to_date = log.check_out
				res.stays[0].nights = log.nights
				res.stays[0].room_type = room_type
			res.save(ignore_permissions=True)
			log.status = "Modified"
			log.processed_at = now_datetime()
			log.save(ignore_permissions=True)
			frappe.db.commit()
			if settings.auto_sync_availability:
				trigger_availability_push(room_type)
			return {"status": "modified", "reservation": res.name}

	# 6. Create New Hotel Reservation
	remarks = (
		f"OTA Booking from {log.ota_source}\n"
		f"OTA Booking ID: {log.ota_booking_id}\n"
		f"Guest: {log.guest_name} | {log.guest_phone or 'No phone'} | {log.guest_email or 'No email'}\n"
		f"Payment Status: {log.payment_status or 'N/A'} (Collect: {log.payment_collect_type or 'Hotel'})"
	)

	nights = max(date_diff(log.check_out, log.check_in), 1)
	rate_per_night = flt(log.total_amount / nights, 2) if nights > 0 and log.total_amount else 0.0

	res = frappe.new_doc("Hotel Reservation")
	res.company = company
	res.customer = customer_name
	res.room_type = room_type
	res.rate_plan = rate_plan
	res.status = ReservationStatus.RESERVED
	res.check_in_date = log.check_in
	res.check_out_date = log.check_out
	res.adults = log.adults or 1
	res.children = log.children or 0
	res.estimated_total = log.total_amount
	res.balance = log.total_amount
	res.remarks = remarks
	res.ota_source = log.ota_source
	res.ota_booking_id = log.ota_booking_id
	res.ota_commission = log.commission
	res.ota_booking_log = log.name

	# Append stay segment
	res.append("stays", {
		"room_type": room_type,
		"from_date": log.check_in,
		"to_date": log.check_out,
		"rate": rate_per_night,
		"nights": nights
	})

	res.flags.ignore_permissions = True
	res.insert()

	# Link reservation back to log
	log.reservation = res.name
	log.status = "Processed"
	log.processed_at = now_datetime()
	log.save(ignore_permissions=True)
	frappe.db.commit()

	# Emit console update so Front Desk UI reflects the new booking in real-time
	try:
		from hospitality_core.api.console import emit_console_update
		emit_console_update("reservation_created", {"reservation": res.name, "room": None, "source": log.ota_source})
	except Exception:
		pass

	# Trigger availability update to Channex
	if settings.auto_sync_availability:
		trigger_availability_push(room_type)

	return {"status": "success", "reservation": res.name}


def get_or_create_ota_customer(name, email, phone, ota_settings):
	"""Matches existing Customer by email or mobile, or creates a new one."""
	filters = {"is_hotel_guest": 1}
	if email:
		existing = frappe.db.get_value("Customer", {"email_id": email, "is_hotel_guest": 1}, "name")
		if existing:
			return existing
	if phone:
		existing = frappe.db.get_value("Customer", {"mobile_no": phone, "is_hotel_guest": 1}, "name")
		if existing:
			return existing

	cust = frappe.new_doc("Customer")
	cust.customer_name = name or "OTA Guest"
	cust.customer_type = "Individual"
	cust.is_hotel_guest = 1
	cust.email_id = email
	cust.mobile_no = phone
	cust.customer_group = ota_settings.ota_customer_group or get_settings().guest_customer_group or None
	cust.territory = ota_settings.ota_territory or get_settings().guest_territory or None
	cust.insert(ignore_permissions=True)
	return cust.name


# ---------------------------------------------------------------- Acknowledge Booking
def acknowledge_booking_revision(revision_id):
	"""
	Acknowledges a booking revision to Channex.
	Mandatory: if not acknowledged, Channex keeps re-sending it.
	"""
	if not revision_id:
		return False

	try:
		headers = get_api_headers()
		url = get_api_url(f"booking_revisions/{revision_id}/ack")
		resp = requests.post(url, headers=headers, json={}, timeout=15)
		return resp.status_code in (200, 204)
	except Exception as e:
		frappe.log_error(title="OTA: Acknowledge failed", message=f"Revision {revision_id}: {str(e)}")
		return False


# ---------------------------------------------------------------- Backup Pull Feed
@frappe.whitelist()
def pull_booking_revisions():
	"""
	Checks the Channex Booking Revisions Feed for new/updated bookings.
	Runs every 15-20 minutes via scheduler as backup to webhooks.
	Can also be called manually from Desk.
	"""
	settings = get_ota_settings()
	if not settings.enabled:
		return {"status": "skipped", "message": "OTA Integration is not enabled"}

	headers = get_api_headers()
	url = get_api_url("booking_revisions/feed")

	try:
		resp = requests.get(url, headers=headers, timeout=30)
		if resp.status_code != 200:
			log_ota_error(f"Feed error HTTP {resp.status_code}: {resp.text[:200]}")
			return {"status": "error", "code": resp.status_code}

		data = resp.json().get("data", [])
		processed_count = 0

		for item in data:
			rev_id = item.get("id")
			attrs = item.get("attributes") or item
			attrs["revision_id"] = rev_id
			res = handle_booking_revision_record(attrs, revision_id=rev_id)
			if res:
				processed_count += 1

		# Update last pull timestamp
		frappe.db.set_single_value("OTA Settings", {
			"last_pull_at": now_datetime(),
			"connection_status": "Connected"
		})
		frappe.db.commit()

		return {"status": "success", "processed": processed_count, "total_received": len(data)}
	except Exception as e:
		frappe.log_error(title="OTA: Pull revisions failed", message=frappe.get_traceback())
		log_ota_error(f"Pull revisions failed: {str(e)[:300]}")
		return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------- Availability Push
@frappe.whitelist()
def push_availability(room_type=None, start_date=None, end_date=None):
	"""
	Pushes available room counts to Channex for mapped room types over a date range.
	Channex endpoint: POST /api/v1/availability
	"""
	settings = get_ota_settings()
	if not settings.enabled:
		return {"status": "skipped", "message": "OTA Integration is disabled"}
	if not settings.channex_property_id:
		frappe.throw(_("Channex Property ID is not configured in OTA Settings."))

	start = getdate(start_date) if start_date else getdate(nowdate())
	end = getdate(end_date) if end_date else add_days(start, 90)

	room_types_to_sync = []
	for row in settings.room_type_map:
		if row.channex_room_type_id:
			if not room_type or row.room_type == room_type:
				room_types_to_sync.append((row.room_type, row.channex_room_type_id))

	if not room_types_to_sync:
		return {"status": "skipped", "message": "No mapped room types with Channex IDs"}

	values = []
	days = date_diff(end, start)

	for local_rt, channex_rt_id in room_types_to_sync:
		for i in range(days):
			d = add_days(start, i)
			d_next = add_days(d, 1)
			avail_info = get_room_type_availability(local_rt, d, d_next)
			free_count = avail_info.get("available", 0)

			values.append({
				"property_id": settings.channex_property_id,
				"room_type_id": channex_rt_id,
				"date_from": str(d),
				"date_to": str(d),
				"availability": free_count
			})

	if not values:
		return {"status": "skipped", "message": "No availability values generated"}

	headers = get_api_headers()
	url = get_api_url("availability")

	# Channex accepts batch updates
	batch_size = 500
	success_batches = 0

	for i in range(0, len(values), batch_size):
		chunk = values[i:i + batch_size]
		try:
			resp = requests.post(url, headers=headers, json={"values": chunk}, timeout=30)
			if resp.status_code in (200, 201, 204):
				success_batches += 1
			else:
				log_ota_error(f"Availability push error HTTP {resp.status_code}: {resp.text[:300]}")
		except Exception as e:
			log_ota_error(f"Availability push error: {str(e)[:300]}")
			frappe.log_error(title="OTA: Availability Push Error", message=str(e))

	frappe.db.set_single_value("OTA Settings", "last_push_at", now_datetime())
	frappe.db.commit()

	return {
		"status": "success",
		"pushed_records": len(values),
		"batches": success_batches,
		"date_range": f"{start} to {end}"
	}


def trigger_availability_push(room_type=None):
	"""Enqueues availability push to avoid blocking document lifecycle."""
	try:
		frappe.enqueue(
			"hospitality_core.api.ota.push_availability",
			room_type=room_type,
			now=frappe.flags.in_test,
			enqueue_after_commit=True
		)
	except Exception:
		pass


# ---------------------------------------------------------------- Rate & Restrictions Push
@frappe.whitelist()
def push_rates(rate_plan=None, start_date=None, end_date=None):
	"""
	Pushes daily prices and restrictions to Channex for mapped rate plans.
	Channex endpoint: POST /api/v1/restrictions
	"""
	settings = get_ota_settings()
	if not settings.enabled:
		return {"status": "skipped", "message": "OTA Integration is disabled"}
	if not settings.channex_property_id:
		frappe.throw(_("Channex Property ID is not configured in OTA Settings."))

	start = getdate(start_date) if start_date else getdate(nowdate())
	end = getdate(end_date) if end_date else add_days(start, 90)

	rate_plans_to_sync = []
	for row in settings.rate_plan_map:
		if row.channex_rate_plan_id:
			if not rate_plan or row.rate_plan == rate_plan:
				rate_plans_to_sync.append((row.rate_plan, row.channex_rate_plan_id))

	if not rate_plans_to_sync:
		return {"status": "skipped", "message": "No mapped rate plans with Channex IDs"}

	values = []
	days = date_diff(end, start)

	for local_rp, channex_rp_id in rate_plans_to_sync:
		rp_doc = frappe.get_doc("Room Rate Plan", local_rp)
		base_rate = flt(rp_doc.rate)
		min_stay = cint(rp_doc.get("free_cancellation_hours") or 1)

		for i in range(days):
			d = add_days(start, i)
			values.append({
				"property_id": settings.channex_property_id,
				"rate_plan_id": channex_rp_id,
				"date_from": str(d),
				"date_to": str(d),
				"rate": base_rate,
				"min_stay_arrival": 1,
				"closed_to_arrival": False,
				"closed_to_departure": False,
				"stop_sell": not bool(rp_doc.active)
			})

	if not values:
		return {"status": "skipped", "message": "No rate values generated"}

	headers = get_api_headers()
	url = get_api_url("restrictions")

	batch_size = 500
	success_batches = 0

	for i in range(0, len(values), batch_size):
		chunk = values[i:i + batch_size]
		try:
			resp = requests.post(url, headers=headers, json={"values": chunk}, timeout=30)
			if resp.status_code in (200, 201, 204):
				success_batches += 1
			else:
				log_ota_error(f"Rate push error HTTP {resp.status_code}: {resp.text[:300]}")
		except Exception as e:
			log_ota_error(f"Rate push error: {str(e)[:300]}")
			frappe.log_error(title="OTA: Rate Push Error", message=str(e))

	frappe.db.set_single_value("OTA Settings", "last_push_at", now_datetime())
	frappe.db.commit()

	return {"status": "success", "records": len(values), "batches": success_batches}


# ---------------------------------------------------------------- Webhook Registration Helper
@frappe.whitelist()
def register_webhook():
	"""
	Registers our webhook URL directly on Channex via API.
	"""
	settings = frappe.get_single("OTA Settings")
	if not settings.api_key:
		frappe.throw(_("Please configure the Channex API Key first."))
	if not settings.channex_property_id:
		frappe.throw(_("Please configure the Channex Property ID first."))

	site_url = frappe.utils.get_url()
	webhook_endpoint = f"{site_url}/api/method/hospitality_core.api.ota.webhook"

	headers = get_api_headers()
	url = get_api_url("webhooks")

	payload = {
		"webhook": {
			"property_id": settings.channex_property_id,
			"event_mask": "*",
			"callback_url": webhook_endpoint,
			"is_active": True,
			"send_data": True
		}
	}

	try:
		resp = requests.post(url, headers=headers, json=payload, timeout=20)
		if resp.status_code in (200, 201):
			res_data = resp.json().get("data", {})
			webhook_id = res_data.get("id")
			frappe.db.set_single_value("OTA Settings", {
				"webhook_url": webhook_endpoint,
				"channex_webhook_id": webhook_id,
				"webhook_registered": 1
			})
			frappe.db.commit()
			return {"status": "success", "webhook_id": webhook_id, "url": webhook_endpoint}
		elif resp.status_code == 422:
			# Check if webhook for this callback_url already exists on Channex
			get_resp = requests.get(url, headers=headers, timeout=15)
			if get_resp.status_code == 200:
				existing_webhooks = get_resp.json().get("data", [])
				for wh in existing_webhooks:
					wh_attrs = wh.get("attributes", {})
					if wh_attrs.get("callback_url") == webhook_endpoint:
						webhook_id = wh.get("id")
						frappe.db.set_single_value("OTA Settings", {
							"webhook_url": webhook_endpoint,
							"channex_webhook_id": webhook_id,
							"webhook_registered": 1
						})
						frappe.db.commit()
						return {
							"status": "success",
							"webhook_id": webhook_id,
							"url": webhook_endpoint,
							"message": _("Existing webhook reused and linked.")
						}
			frappe.throw(_("Channex returned HTTP {0}: {1}").format(resp.status_code, resp.text[:200]))
		else:
			frappe.throw(_("Channex returned HTTP {0}: {1}").format(resp.status_code, resp.text[:200]))
	except Exception as e:
		frappe.throw(_("Failed to register webhook: {0}").format(str(e)))


# ---------------------------------------------------------------- Doc Event Hooks
def on_reservation_update(doc, method=None):
	"""Triggered on Hotel Reservation update/trash to keep Channex inventory in sync."""
	try:
		settings = get_ota_settings()
		if settings.enabled and settings.auto_sync_availability:
			trigger_availability_push(doc.room_type)
	except Exception:
		pass


def on_room_update(doc, method=None):
	"""Triggered on Hotel Room update to keep Channex inventory in sync."""
	try:
		settings = get_ota_settings()
		if settings.enabled and settings.auto_sync_availability:
			trigger_availability_push(doc.room_type)
	except Exception:
		pass


def on_rate_plan_update(doc, method=None):
	"""Triggered on Room Rate Plan update to push new rates to Channex."""
	try:
		settings = get_ota_settings()
		if settings.enabled and settings.auto_sync_rates:
			frappe.enqueue(
				"hospitality_core.api.ota.push_rates",
				rate_plan=doc.name,
				now=frappe.flags.in_test,
				enqueue_after_commit=True
			)
	except Exception:
		pass
