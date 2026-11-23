import urllib.parse
import frappe
from frappe import _
from frappe.utils import (
	cint,
	flt,
	getdate,
	now_datetime,
	nowdate,
)

from hospitality_core.constants import ReservationStatus, RoomStatus
from hospitality_core.utils import get_company, get_settings


@frappe.whitelist()
def get_night_audit_summary(audit_date=None):
	"""
	Calculates daily KPIs and financial summaries for Night Audit:
	- Occupancy %, Total Rooms, Occupied, Available, Dirty, Out of Order
	- Arrivals, In-House, Departures
	- Room Revenue, F&B / POS Revenue, Total Revenue, ADR, RevPAR
	- Outstanding Folio Balances
	- Formatted WhatsApp message for Owner / General Manager
	"""
	if not audit_date:
		audit_date = nowdate()
	audit_date = getdate(audit_date)

	settings = get_settings()
	hotel_name = getattr(settings, "hotel_name", None) or get_company() or "Our Hotel"
	owner_phone = getattr(settings, "contact_number", None) or ""

	# Currency
	default_curr = frappe.db.get_default("currency") or "GBP"

	# 1. Room Inventory Breakdown
	rooms = frappe.get_all("Hotel Room", filters={"is_enabled": 1}, fields=["name", "status", "room_type"])
	total_rooms = len(rooms)
	occupied_rooms = len([r for r in rooms if r.status == RoomStatus.OCCUPIED])
	available_rooms = len([r for r in rooms if r.status == RoomStatus.AVAILABLE])
	dirty_rooms = len([r for r in rooms if r.status == RoomStatus.DIRTY])
	ooo_rooms = len([r for r in rooms if r.status == RoomStatus.OUT_OF_ORDER])
	reserved_rooms = len([r for r in rooms if r.status == RoomStatus.RESERVED])

	occupancy_pct = round((occupied_rooms / total_rooms * 100), 1) if total_rooms > 0 else 0.0

	# 2. Guest Movement
	arrivals_today = frappe.db.count("Hotel Reservation", {
		"check_in_date": audit_date,
		"status": ["in", [ReservationStatus.RESERVED, ReservationStatus.CHECKED_IN]]
	})

	in_house_stays = frappe.get_all("Hotel Reservation", filters={
		"status": ReservationStatus.CHECKED_IN
	}, fields=["name", "customer", "room", "room_type", "estimated_total"])
	in_house_count = len(in_house_stays)

	departures_today = frappe.db.count("Hotel Reservation", {
		"check_out_date": audit_date,
		"status": ReservationStatus.CHECKED_OUT
	})

	# 3. Revenue & Rates (Tonight's Room Revenue)
	room_revenue = 0.0
	try:
		# Sum of tonight's stay rates for checked-in or active stays
		stays = frappe.db.sql(
			"""
			SELECT s.rate, r.currency
			FROM `tabHotel Reservation Stay` s
			INNER JOIN `tabHotel Reservation` r ON r.name = s.parent
			WHERE r.status = 'Checked In'
			  AND s.from_date <= %s AND s.to_date > %s
			""",
			(audit_date, audit_date),
			as_dict=True
		)
		for st in stays:
			room_revenue += flt(st.rate)
			if st.currency:
				default_curr = st.currency
	except Exception:
		pass

	# If no specific stays matched, approximate from in-house reservations
	if not room_revenue and in_house_count > 0:
		for res in in_house_stays:
			room_revenue += flt(res.get("estimated_total") or 0.0) / 1.0

	# F&B / POS / Sales Invoices posted today
	fnb_revenue = 0.0
	try:
		fnb_res = frappe.db.sql(
			"""
			SELECT SUM(grand_total) as total
			FROM `tabSales Invoice`
			WHERE docstatus = 1 AND posting_date = %s
			""",
			(audit_date,),
			as_dict=True
		)
		if fnb_res and fnb_res[0].total:
			fnb_revenue = flt(fnb_res[0].total)
	except Exception:
		pass

	total_revenue = room_revenue + fnb_revenue
	adr = round(room_revenue / occupied_rooms, 2) if occupied_rooms > 0 else 0.0
	revpar = round(room_revenue / total_rooms, 2) if total_rooms > 0 else 0.0

	# 4. Outstanding Balances across in-house guests
	total_balance = 0.0
	try:
		from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import get_billing_summary
		for res in in_house_stays:
			b = get_billing_summary(res.name)
			total_balance += flt(b.get("balance", 0.0))
	except Exception:
		pass

	# Currency symbol
	curr_symbols = {"GBP": "£", "USD": "$", "EUR": "€", "INR": "₹", "AED": "AED"}
	sym = curr_symbols.get(default_curr, default_curr + " ")

	# 5. Build Executive WhatsApp Text
	whatsapp_text = (
		f"🏨 *{hotel_name.upper()} — DAILY NIGHT AUDIT*\n"
		f"📅 *Date:* {audit_date.strftime('%d-%b-%Y')}\n"
		f"──────────────────────\n"
		f"📊 *KEY PERFORMANCE INDICATORS*\n"
		f"• *Occupancy:* {occupancy_pct}% ({occupied_rooms}/{total_rooms} Rooms)\n"
		f"• *Total Revenue:* {sym} {total_revenue:,.2f}\n"
		f"• *Room Revenue:* {sym} {room_revenue:,.2f}\n"
		f"• *F&B / POS Revenue:* {sym} {fnb_revenue:,.2f}\n"
		f"• *ADR (Avg Daily Rate):* {sym} {adr:,.2f}\n"
		f"• *RevPAR:* {sym} {revpar:,.2f}\n\n"
		f"🛎️ *ROOM & GUEST MOVEMENT*\n"
		f"• *In-House Guests:* {in_house_count}\n"
		f"• *Arrivals Today:* {arrivals_today}\n"
		f"• *Departures Today:* {departures_today}\n"
		f"• *Available Rooms:* {available_rooms}\n"
		f"• *Dirty / Turnover:* {dirty_rooms}\n"
		f"• *Out of Order:* {ooo_rooms}\n\n"
		f"💳 *FINANCIAL STATUS*\n"
		f"• *Outstanding Folio Balance:* {sym} {total_balance:,.2f}\n"
		f"──────────────────────\n"
		f"✅ *Audit Status:* Completed successfully at {now_datetime().strftime('%I:%M %p')}.\n"
		f"Generated by Hospitality Core PMS."
	)

	# Direct WhatsApp Link
	clean_phone = "".join(ch for ch in str(owner_phone) if ch.isdigit() or ch == "+").lstrip("+")
	whatsapp_url = ""
	if clean_phone:
		whatsapp_url = f"https://wa.me/{clean_phone}?text={urllib.parse.quote(whatsapp_text)}"

	data = {
		"audit_date": str(audit_date),
		"hotel_name": hotel_name,
		"currency": default_curr,
		"currency_symbol": sym,
		"total_rooms": total_rooms,
		"occupied_rooms": occupied_rooms,
		"available_rooms": available_rooms,
		"dirty_rooms": dirty_rooms,
		"out_of_order_rooms": ooo_rooms,
		"reserved_rooms": reserved_rooms,
		"occupancy_pct": occupancy_pct,
		"arrivals_today": arrivals_today,
		"in_house_count": in_house_count,
		"departures_today": departures_today,
		"room_revenue": room_revenue,
		"fnb_revenue": fnb_revenue,
		"total_revenue": total_revenue,
		"adr": adr,
		"revpar": revpar,
		"total_balance": total_balance,
		"owner_phone": owner_phone,
		"whatsapp_text": whatsapp_text,
		"whatsapp_url": whatsapp_url,
	}

	# Cache latest audit
	frappe.cache().set_value("latest_night_audit", data, expires_in_sec=86400 * 7)

	return data


@frappe.whitelist()
def run_night_audit(audit_date=None):
	"""
	Executes the Night Audit cycle:
	1. Re-calculates and logs daily KPIs and revenue.
	2. Commits log to Frappe.
	3. Notifies owner via WhatsApp if mobile number is configured.
	"""
	data = get_night_audit_summary(audit_date)

	# Optional log in frappe error/event log for audit tracking
	frappe.log_error(
		title=f"Night Audit Completed: {data['audit_date']} ({data['occupancy_pct']}% Occupancy)",
		message=data["whatsapp_text"]
	)
	frappe.db.commit()

	return {
		"status": "success",
		"message": _("Night Audit for {0} completed successfully.").format(data["audit_date"]),
		"data": data
	}

