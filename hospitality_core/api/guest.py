import base64
import hashlib
import hmac
import json
import urllib.parse

import frappe
from frappe import _
from frappe.utils import (
	cint,
	date_diff,
	flt,
	get_url,
	getdate,
	now_datetime,
	nowdate,
)

from hospitality_core.utils import get_company, get_settings


def generate_guest_token(doctype, docname):
	"""Generates a secure HMAC-signed URL-safe token for guest pre-check-in."""
	secret = frappe.local.conf.get("encryption_key") or "hospitality_guest_key"
	payload = f"{doctype}:{docname}"
	sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
	raw = f"{doctype}:{docname}:{sig}"
	return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8").rstrip("=")


def verify_guest_token(token):
	"""Decodes and validates a guest pre-check-in token. Returns (doctype, docname) or (None, None)."""
	try:
		if not token:
			return None, None
		padding = "=" * (4 - len(token) % 4)
		raw = base64.urlsafe_b64decode((token + padding).encode("utf-8")).decode("utf-8")
		parts = raw.split(":")
		if len(parts) != 3:
			return None, None
		doctype, docname, sig = parts
		secret = frappe.local.conf.get("encryption_key") or "hospitality_guest_key"
		expected = hmac.new(secret.encode("utf-8"), f"{doctype}:{docname}".encode("utf-8"), hashlib.sha256).hexdigest()[:16]
		if hmac.compare_digest(sig, expected):
			return doctype, docname
	except Exception:
		pass
	return None, None


@frappe.whitelist(allow_guest=True)
def get_precheckin_details(token):
	"""Fetches reservation details for the guest pre-check-in portal without requiring login."""
	doctype, docname = verify_guest_token(token)
	if not doctype or not docname:
		frappe.throw(_("Invalid or expired pre-check-in link."), frappe.PermissionError)

	settings = get_settings()
	hotel_name = getattr(settings, "hotel_name", None) or get_company() or "Our Hotel"
	hotel_phone = getattr(settings, "contact_number", None) or ""
	hotel_address = getattr(settings, "address_line", None) or ""

	if doctype == "Hotel Reservation":
		doc = frappe.get_doc("Hotel Reservation", docname)
		return {
			"doctype": "Hotel Reservation",
			"name": doc.name,
			"guest_name": doc.customer or "Guest",
			"phone": frappe.db.get_value("Customer", doc.customer, "mobile_no") or "",
			"check_in_date": str(doc.check_in_date),
			"check_out_date": str(doc.check_out_date),
			"nights": max(date_diff(doc.check_out_date, doc.check_in_date), 1),
			"room_type": doc.room_type,
			"room": doc.room or "",
			"adults": doc.adults or 1,
			"status": doc.status,
			"guest_id_type": doc.guest_id_type or "",
			"guest_id_number": doc.guest_id_number or "",
			"has_id": bool(doc.guest_id_number),
			"hotel_name": hotel_name,
			"hotel_phone": hotel_phone,
			"hotel_address": hotel_address,
		}
	elif doctype == "OTA Reservation":
		doc = frappe.get_doc("OTA Reservation", docname)
		return {
			"doctype": "OTA Reservation",
			"name": doc.name,
			"guest_name": doc.guest_name or "Guest",
			"phone": doc.guest_phone or "",
			"check_in_date": str(doc.check_in_date),
			"check_out_date": str(doc.check_out_date),
			"nights": doc.nights or 1,
			"room_type": doc.room_type_name or "Standard",
			"adults": doc.adults or 1,
			"status": doc.status,
			"has_id": False,
			"hotel_name": hotel_name,
			"hotel_phone": hotel_phone,
			"hotel_address": hotel_address,
		}

	frappe.throw(_("Record not found."))


@frappe.whitelist(allow_guest=True)
def submit_precheckin(token, id_type, id_number, arrival_time=None, special_requests=None, id_document_base64=None, filename=None):
	"""
	Saves guest-submitted identity details directly into the reservation.
	Handles optional base64 photo/document upload from guest phone camera.
	"""
	doctype, docname = verify_guest_token(token)
	if not doctype or not docname:
		frappe.throw(_("Invalid or expired pre-check-in link."), frappe.PermissionError)

	id_type = (id_type or "").strip()
	id_number = (id_number or "").strip()
	if not id_type or not id_number:
		frappe.throw(_("Please provide both ID Type and ID Number."))

	file_url = None
	if id_document_base64:
		try:
			# Remove header if present (e.g. data:image/jpeg;base64,...)
			if "," in id_document_base64:
				id_document_base64 = id_document_base64.split(",", 1)[1]
			file_data = base64.b64decode(id_document_base64)
			safe_name = filename or f"guest_id_{docname}.jpg"
			file_doc = frappe.get_doc({
				"doctype": "File",
				"file_name": safe_name,
				"attached_to_doctype": doctype,
				"attached_to_name": docname,
				"content": file_data,
				"is_private": 1
			})
			file_doc.save(ignore_permissions=True)
			file_url = file_doc.file_url
		except Exception as e:
			frappe.log_error(title="Pre-checkin file upload error", message=str(e))

	note_parts = []
	if arrival_time:
		note_parts.append(f"Expected Arrival: {arrival_time}")
	if special_requests:
		note_parts.append(f"Guest Requests: {special_requests}")
	notes = " | ".join(note_parts)

	settings = get_settings()
	wifi_info = {
		"network": getattr(settings, "hotel_name", None) or "Hotel Free WiFi",
		"password": getattr(settings, "wifi_password", None) or "Welcome123"
	}

	if doctype == "Hotel Reservation":
		updates = {
			"guest_id_type": id_type,
			"guest_id_number": id_number,
		}
		if file_url:
			updates["guest_id_document"] = file_url
		if notes:
			old_remarks = frappe.db.get_value("Hotel Reservation", docname, "remarks") or ""
			updates["remarks"] = f"{old_remarks}\n[Pre-Check-in]: {notes}".strip()

		frappe.db.set_value("Hotel Reservation", docname, updates)
		frappe.db.commit()

		return {
			"status": "success",
			"message": _("Pre-check-in completed successfully! You can proceed directly to key collection upon arrival."),
			"reservation": docname,
			"wifi": wifi_info
		}

	elif doctype == "OTA Reservation":
		old_remarks = frappe.db.get_value("OTA Reservation", docname, "remarks") or ""
		new_remarks = f"{old_remarks}\n[Pre-Check-in ID]: {id_type} {id_number}".strip()
		if notes:
			new_remarks += f" ({notes})"

		frappe.db.set_value("OTA Reservation", docname, {
			"remarks": new_remarks
		})
		frappe.db.commit()

		return {
			"status": "success",
			"message": _("Pre-check-in details received! Your booking is ready for express check-in."),
			"reservation": docname,
			"wifi": wifi_info
		}


@frappe.whitelist()
def get_whatsapp_links(reservation_name=None, ota_reservation_name=None):
	"""
	Builds personalized WhatsApp messages and 1-click wa.me links for:
	1. Welcome & Pre-Check-in link (skip the front desk line)
	2. Digital Folio Bill & Online Payment link
	3. Hotel WiFi & Stay Info
	"""
	settings = get_settings()
	hotel_name = getattr(settings, "hotel_name", None) or get_company() or "Our Hotel"
	hotel_phone = getattr(settings, "contact_number", None) or ""
	base_url = get_url().rstrip("/")

	target_doctype = None
	target_name = None
	guest_name = ""
	guest_phone = ""
	dates_str = ""
	nights = 1
	room_type = ""
	currency = frappe.db.get_default("currency") or "GBP"
	balance = 0.0

	curr_symbols = {"GBP": "£", "USD": "$", "EUR": "€", "INR": "₹", "AED": "AED"}

	if reservation_name:
		target_doctype = "Hotel Reservation"
		target_name = reservation_name
		doc = frappe.get_doc("Hotel Reservation", reservation_name)
		guest_name = doc.customer or "Guest"
		guest_phone = frappe.db.get_value("Customer", doc.customer, "mobile_no") or ""
		dates_str = f"{doc.check_in_date} to {doc.check_out_date}"
		nights = max(date_diff(doc.check_out_date, doc.check_in_date), 1)
		room_type = doc.room_type or ""
		from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import get_billing_summary
		b = get_billing_summary(doc.name)
		balance = flt(b.get("balance", 0.0))

	elif ota_reservation_name:
		target_doctype = "OTA Reservation"
		target_name = ota_reservation_name
		doc = frappe.get_doc("OTA Reservation", ota_reservation_name)
		guest_name = doc.guest_name or "Guest"
		guest_phone = doc.guest_phone or ""
		dates_str = f"{doc.check_in_date} to {doc.check_out_date}"
		nights = doc.nights or 1
		room_type = doc.room_type_name or ""
		currency = doc.currency or currency
		balance = flt(doc.total_amount or 0.0)

	sym = curr_symbols.get(currency, currency + " ")

	# Generate secure pre-check-in link
	token = generate_guest_token(target_doctype, target_name)
	precheckin_url = f"{base_url}/api/method/hospitality_core.api.guest.portal?token={token}"

	# Clean phone number for WhatsApp
	clean_phone = "".join(ch for ch in str(guest_phone) if ch.isdigit() or ch == "+").lstrip("+")

	# Message 1: Welcome & Pre-check-in Link
	msg_welcome = (
		f"Hello *{guest_name}*, welcome to *{hotel_name}*! 🏨\n\n"
		f"Your booking for *{dates_str}* ({nights} night(s), {room_type}) is confirmed.\n\n"
		f"⚡ *Skip the front desk queue:* Tap here to complete your 1-minute digital pre-check-in & ID upload:\n"
		f"{precheckin_url}\n\n"
		f"We look forward to hosting you! Feel free to reply here if you have any questions."
	)

	# Message 2: In-House WiFi Pass & Concierge
	msg_wifi = (
		f"Dear *{guest_name}*, welcome to your room at *{hotel_name}*! 🌟\n\n"
		f"📶 *Free High-Speed WiFi:*\n"
		f"• Network: *{hotel_name} Guest*\n"
		f"• Password: *Welcome123*\n\n"
		f"For room service, extra towels, or front desk assistance, reply directly to this message or dial front desk at {hotel_phone}."
	)

	# Message 3: Checkout Folio & Payment
	msg_bill = (
		f"Dear *{guest_name}*, thank you for staying with us at *{hotel_name}*! 🙏\n\n"
		f"🧾 *Room Folio Summary:*\n"
		f"• Current Outstanding Balance: *{sym} {balance:,.2f}*\n\n"
		f"We hope you enjoyed your stay. Have a safe journey ahead!"
	)

	make_url = lambda text: f"https://wa.me/{clean_phone}?text={urllib.parse.quote(text)}" if clean_phone else ""

	return {
		"guest_name": guest_name,
		"guest_phone": guest_phone,
		"clean_phone": clean_phone,
		"precheckin_url": precheckin_url,
		"messages": {
			"welcome": {
				"title": _("Pre-Check-in Invitation"),
				"text": msg_welcome,
				"url": make_url(msg_welcome)
			},
			"wifi": {
				"title": _("WiFi & Digital Pass"),
				"text": msg_wifi,
				"url": make_url(msg_wifi)
			},
			"bill": {
				"title": _("Folio Bill & Checkout"),
				"text": msg_bill,
				"url": make_url(msg_bill)
			}
		}
	}


@frappe.whitelist(allow_guest=True)
def portal(token=None):
	"""
	Renders an elegant, modern mobile web page for guest self pre-check-in.
	Works on all smartphones without downloading an app.
	"""
	if not token or token == "preview":
		settings = get_settings()
		hotel_name = getattr(settings, "hotel_name", None) or get_company() or "Sky Hotel"
		hotel_phone = getattr(settings, "contact_number", None) or ""
		hotel_address = getattr(settings, "address_line", None) or ""
		details = {
			"doctype": "Hotel Reservation",
			"name": "DEMO-PREVIEW",
			"guest_name": "Demo Guest",
			"phone": "+44 7000 123456",
			"check_in_date": nowdate(),
			"check_out_date": nowdate(),
			"nights": 2,
			"room_type": "Demo Double",
			"room": "101",
			"adults": 2,
			"status": "Reserved",
			"guest_id_type": "",
			"guest_id_number": "",
			"has_id": False,
			"hotel_name": hotel_name,
			"hotel_phone": hotel_phone,
			"hotel_address": hotel_address,
		}
	else:
		doctype, docname = verify_guest_token(token)
		if not doctype or not docname:
			html_err = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Link Expired</title><meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#f8fafc;color:#334155;}
.box{background:white;padding:32px 24px;border-radius:16px;box-shadow:0 4px 16px rgba(0,0,0,0.06);text-align:center;max-width:420px;margin:16px;}
h3{color:#dc2626;margin:0 0 10px 0;font-size:18px;}p{font-size:14px;color:#64748b;line-height:1.5;margin:0;}</style></head>
<body><div class="box"><h3>⚠️ Link Expired or Invalid</h3><p>This pre-check-in link is expired or invalid. Please contact the front desk for assistance.</p></div></body></html>"""
			frappe.response["type"] = "raw"
			frappe.response["response"] = html_err
			frappe.response["content_type"] = "text/html; charset=utf-8"
			return html_err

		details = get_precheckin_details(token)

	html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Express Pre-Check-in · {details['hotel_name']}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <style>
        :root {{
            --primary: #0284c7;
            --primary-dark: #0369a1;
            --bg: #f8fafc;
            --card-bg: #ffffff;
            --text: #0f172a;
        }}
        body {{
            background-color: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            padding: 16px 12px 40px;
        }}
        .guest-container {{
            max-width: 480px;
            margin: 0 auto;
        }}
        .hotel-header {{
            text-align: center;
            padding: 20px 0 16px;
        }}
        .hotel-badge {{
            display: inline-block;
            background: #e0f2fe;
            color: var(--primary-dark);
            font-size: 11px;
            font-weight: 700;
            padding: 4px 12px;
            border-radius: 20px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 8px;
        }}
        .hotel-title {{
            font-size: 22px;
            font-weight: 800;
            color: #0f172a;
            margin: 0;
        }}
        .stay-card {{
            background: var(--card-bg);
            border: 1px solid #e2e8f0;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.04);
        }}
        .stay-dates {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #f1f5f9;
            padding: 12px 16px;
            border-radius: 12px;
            margin-top: 14px;
        }}
        .stay-date-box {{
            text-align: left;
        }}
        .stay-date-box.right {{
            text-align: right;
        }}
        .stay-lbl {{
            font-size: 11px;
            color: #64748b;
            text-transform: uppercase;
            font-weight: 600;
        }}
        .stay-val {{
            font-size: 14px;
            font-weight: 700;
            color: #0f172a;
        }}
        .form-card {{
            background: var(--card-bg);
            border: 1px solid #e2e8f0;
            border-radius: 16px;
            padding: 22px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.04);
        }}
        .form-label {{
            font-size: 13px;
            font-weight: 600;
            color: #334155;
            margin-bottom: 6px;
        }}
        .form-control, .form-select {{
            border-radius: 10px;
            padding: 10px 14px;
            font-size: 14px;
            border: 1.5px solid #cbd5e1;
        }}
        .form-control:focus, .form-select:focus {{
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.15);
        }}
        .btn-submit {{
            background: var(--primary);
            color: white;
            font-size: 16px;
            font-weight: 700;
            padding: 14px;
            border-radius: 12px;
            border: none;
            width: 100%;
            margin-top: 10px;
            transition: background 0.15s ease;
        }}
        .btn-submit:hover {{
            background: var(--primary-dark);
        }}
        .pass-card {{
            display: none;
            background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
            color: white;
            border-radius: 16px;
            padding: 24px 20px;
            margin-top: 20px;
            box-shadow: 0 10px 25px rgba(2, 132, 199, 0.3);
            text-align: center;
        }}
        .pass-title {{
            font-size: 18px;
            font-weight: 800;
            margin-bottom: 4px;
        }}
        .pass-subtitle {{
            font-size: 12px;
            opacity: 0.9;
            margin-bottom: 20px;
        }}
        .pass-wifi {{
            background: rgba(255, 255, 255, 0.15);
            backdrop-filter: blur(8px);
            padding: 14px;
            border-radius: 12px;
            margin-bottom: 16px;
            text-align: left;
        }}
    </style>
</head>
<body>
    <div class="guest-container">
        <div class="hotel-header">
            <span class="hotel-badge">Instant Express Check-in</span>
            <h1 class="hotel-title">{details['hotel_name']}</h1>
        </div>

        <div class="stay-card">
            <div style="font-size:18px;font-weight:800;">Welcome, {details['guest_name']}! 👋</div>
            <div style="font-size:13px;color:#64748b;margin-top:2px;">Room: <b>{details['room_type']}</b> · {details['adults']} Adult(s)</div>

            <div class="stay-dates">
                <div class="stay-date-box">
                    <div class="stay-lbl">Check-In</div>
                    <div class="stay-val">{details['check_in_date']}</div>
                </div>
                <div style="font-size:12px;font-weight:700;color:#0284c7;">{details['nights']} NIGHT(S)</div>
                <div class="stay-date-box right">
                    <div class="stay-lbl">Check-Out</div>
                    <div class="stay-val">{details['check_out_date']}</div>
                </div>
            </div>
        </div>

        <div class="form-card" id="form-section">
            <div style="font-size:15px;font-weight:700;margin-bottom:16px;">Fast Identity Verification</div>

            <div class="mb-3">
                <label class="form-label">Photo ID Type *</label>
                <select class="form-select" id="id_type" required>
                    <option value="Aadhaar" selected>Aadhaar Card (India)</option>
                    <option value="Passport">Passport</option>
                    <option value="Driving License">Driving License</option>
                    <option value="Voter ID">Voter ID</option>
                    <option value="National ID">National ID Card</option>
                </select>
            </div>

            <div class="mb-3">
                <label class="form-label">ID Number *</label>
                <input type="text" class="form-control" id="id_number" placeholder="Enter ID number" required value="{details.get('guest_id_number') or ''}">
            </div>

            <div class="mb-3">
                <label class="form-label">Upload Photo of ID (Optional)</label>
                <input type="file" class="form-control" id="id_file" accept="image/*,.pdf" capture="environment">
                <div style="font-size:11px;color:#64748b;margin-top:4px;">Snap a photo of your ID with phone camera.</div>
            </div>

            <div class="mb-3">
                <label class="form-label">Estimated Arrival Time</label>
                <input type="time" class="form-control" id="arrival_time" value="14:00">
            </div>

            <div class="mb-4">
                <label class="form-label">Special Requests (Optional)</label>
                <input type="text" class="form-control" id="special_requests" placeholder="e.g. Quiet room, extra pillow, early check-in">
            </div>

            <button type="button" class="btn-submit" id="btn-submit" onclick="submitPreCheckin()">
                Confirm & Get Digital Pass ⚡
            </button>
        </div>

        <!-- Success Digital Pass Card -->
        <div class="pass-card" id="pass-section">
            <div style="font-size:36px;margin-bottom:8px;">✅</div>
            <div class="pass-title">Pre-Check-in Confirmed!</div>
            <div class="pass-subtitle">Your identity has been pre-verified. Show your name at front desk for instant key collection.</div>

            <div class="pass-wifi" id="wifi-box">
                <div style="font-size:11px;font-weight:700;text-transform:uppercase;opacity:0.8;">Hotel Free WiFi</div>
                <div style="font-weight:700;font-size:14px;margin-top:2px;">Network: <span id="wifi-net">Hotel WiFi</span></div>
                <div style="font-weight:700;font-size:14px;">Password: <span id="wifi-pass">Welcome123</span></div>
            </div>

            <div style="font-size:12px;opacity:0.9;">
                Need help? Call front desk at <b>{details['hotel_phone'] or 'Reception'}</b>
            </div>
        </div>
    </div>

    <script>
        const token = "{token}";

        function submitPreCheckin() {{
            const idType = document.getElementById("id_type").value;
            const idNumber = document.getElementById("id_number").value.trim();
            const arrivalTime = document.getElementById("arrival_time").value;
            const specialRequests = document.getElementById("special_requests").value;
            const fileInput = document.getElementById("id_file");
            const btn = document.getElementById("btn-submit");

            if (!idNumber) {{
                alert("Please enter your ID number.");
                return;
            }}

            btn.disabled = true;
            btn.innerText = "Verifying & Saving...";

            const sendPayload = (base64Content, fileName) => {{
                fetch("/api/method/hospitality_core.api.guest.submit_precheckin", {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify({{
                        token: token,
                        id_type: idType,
                        id_number: idNumber,
                        arrival_time: arrivalTime,
                        special_requests: specialRequests,
                        id_document_base64: base64Content || null,
                        filename: fileName || null
                    }})
                }})
                .then(r => r.json())
                .then(res => {{
                    if (res.message && res.message.status === "success") {{
                        document.getElementById("form-section").style.display = "none";
                        const passSec = document.getElementById("pass-section");
                        passSec.style.display = "block";
                        if (res.message.wifi) {{
                            document.getElementById("wifi-net").innerText = res.message.wifi.network;
                            document.getElementById("wifi-pass").innerText = res.message.wifi.password;
                        }}
                    }} else {{
                        alert(res.exc || res.message || "Failed to submit pre-checkin.");
                        btn.disabled = false;
                        btn.innerText = "Confirm & Get Digital Pass ⚡";
                    }}
                }})
                .catch(err => {{
                    alert("Network error. Please try again.");
                    btn.disabled = false;
                    btn.innerText = "Confirm & Get Digital Pass ⚡";
                }});
            }};

            if (fileInput.files && fileInput.files[0]) {{
                const reader = new FileReader();
                const file = fileInput.files[0];
                reader.onload = function(e) {{
                    sendPayload(e.target.result, file.name);
                }};
                reader.readAsDataURL(file);
            }} else {{
                sendPayload(null, null);
            }}
        }}
    </script>
</body>
</html>
"""
	frappe.response["type"] = "raw"
	frappe.response["response"] = html
	frappe.response["content_type"] = "text/html; charset=utf-8"
	return html

