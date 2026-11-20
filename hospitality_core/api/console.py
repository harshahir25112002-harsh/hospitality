import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate, now_datetime, add_days, date_diff
from hospitality_core.constants import RoomStatus, ReservationStatus
from hospitality_core.utils import get_settings, get_company
from hospitality_core.room_status import set_room_status
from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import (
    get_available_rooms as v1_get_available_rooms,
    get_billing_summary,
    check_in as v1_check_in,
    move_room as v1_move_room,
    cancel_reservation as v1_cancel_reservation,
    check_out as v1_check_out,
    get_room_rate,
    get_room_type_availability as v1_room_type_availability,
    get_available_physical_rooms as v1_physical_rooms,
    validate_reservation_dates,
    validate_guest_capacity,
    mask_id,
)


CONSOLE_ROLES = ("Hospitality User", "System Manager", "Accounts User", "Accounts Manager")


def require_console_access():
    """Only front-desk roles may use the console API (it acts with ignore_permissions)."""
    if frappe.session.user == "Administrator":
        return
    if not set(CONSOLE_ROLES) & set(frappe.get_roles()):
        frappe.throw(_("You do not have access to the Front Desk Console."), frappe.PermissionError)


def emit_console_update(event_type, data):
    """Publishes realtime update to all connected front desk consoles"""
    try:
        frappe.publish_realtime("hotel_console_update", {"type": event_type, "data": data})
    except Exception:
        pass


@frappe.whitelist()
def get_console_data(target_date=None):
    """
    Returns single consolidated payload for the entire front desk console:
    {kpis, rooms[], arrivals[], departures[], in_house[], dirty[], maintenance[], settings}
    """
    require_console_access()
    target_date = getdate(target_date) if target_date else getdate(nowdate())
    settings = get_settings()
    company = settings.company or get_company()

    # 1. Rooms
    rooms = frappe.get_all(
        "Hotel Room",
        fields=["name", "room_number", "room_type", "floor", "status", "current_reservation", "notes"],
        filters={"is_enabled": 1},
        order_by="floor asc, room_number asc"
    )

    # Attach guest details & pending charges to occupied/reserved rooms
    room_map = {r.name: r for r in rooms}
    active_reservations = frappe.db.sql("""
        SELECT r.name, r.customer, c.customer_name as guest_name, r.room, r.room_type,
               r.check_in_date, r.check_out_date, r.status, r.balance
        FROM `tabHotel Reservation` r
        LEFT JOIN `tabCustomer` c ON c.name = r.customer
        WHERE r.status IN ('Reserved', 'Checked In')
    """, as_dict=True)

    res_by_name = {r.name: r for r in active_reservations}
    res_by_room = {}
    for r in active_reservations:
        if r.room and (r.room not in res_by_room or r.status == "Checked In"):
            res_by_room[r.room] = r
    for room in rooms:
        if room.current_reservation and room.current_reservation in res_by_name:
            res_by_room[room.name] = res_by_name[room.current_reservation]

    # Pending room service drafts
    room_service_totals = frappe.db.sql("""
        SELECT hotel_reservation, SUM(grand_total) as total
        FROM `tabSales Invoice`
        WHERE charge_to_room = 1 AND docstatus = 0
        GROUP BY hotel_reservation
    """, as_dict=True)
    rs_by_res = {rs.hotel_reservation: flt(rs.total, 2) for rs in room_service_totals}

    for r in rooms:
        res = res_by_room.get(r.name)
        if res:
            r["guest_name"] = res.guest_name
            r["customer"] = res.customer
            r["reservation_status"] = res.status
            r["balance"] = flt(res.balance, 2)
            r["room_service_pending"] = rs_by_res.get(res.name, 0.0)
            r["check_in_date"] = res.check_in_date
            r["check_out_date"] = res.check_out_date
            r["reservation"] = res.name
        else:
            r["reservation"] = None
            r["guest_name"] = None
            r["customer"] = None
            r["reservation_status"] = None
            r["balance"] = 0.0
            r["room_service_pending"] = 0.0
            r["check_in_date"] = None
            r["check_out_date"] = None

    # 2. Arrivals (expected on target_date)
    arrivals = frappe.db.sql("""
        SELECT r.name, r.customer, c.customer_name as guest_name, r.room, r.room_type,
               r.check_in_date, r.check_out_date, r.status, r.estimated_total, r.total_paid, r.balance
        FROM `tabHotel Reservation` r
        LEFT JOIN `tabCustomer` c ON c.name = r.customer
        WHERE r.check_in_date = %s
        AND r.status = 'Reserved'
        ORDER BY r.name ASC
    """, (target_date,), as_dict=True)

    # 3. Departures (due on target_date)
    departures = frappe.db.sql("""
        SELECT r.name, r.customer, c.customer_name as guest_name, r.room, r.room_type,
               r.check_in_date, r.check_out_date, r.status, r.balance
        FROM `tabHotel Reservation` r
        LEFT JOIN `tabCustomer` c ON c.name = r.customer
        WHERE r.check_out_date = %s
        AND r.status = 'Checked In'
        ORDER BY r.room ASC
    """, (target_date,), as_dict=True)

    # 4. In-House (currently Checked In)
    in_house = frappe.db.sql("""
        SELECT r.name, r.customer, c.customer_name as guest_name, r.room, r.room_type,
               r.check_in_date, r.check_out_date, r.status, r.balance
        FROM `tabHotel Reservation` r
        LEFT JOIN `tabCustomer` c ON c.name = r.customer
        WHERE r.status = 'Checked In'
        ORDER BY r.room ASC
    """, as_dict=True)
    for inh in in_house:
        inh["room_service_pending"] = rs_by_res.get(inh.name, 0.0)

    # 5. Dirty rooms
    dirty_rooms = [r for r in rooms if r.status == RoomStatus.DIRTY]

    # 6. Maintenance / Issues
    maintenance_issues = frappe.db.sql("""
        SELECT name, subject, hotel_room, status, priority, creation
        FROM `tabIssue`
        WHERE hotel_room IS NOT NULL AND status IN ('Open', 'Replied', 'Hold')
        ORDER BY creation DESC
    """, as_dict=True)

    # 7. KPIs
    total_rooms = len(rooms)
    occupied_count = len([r for r in rooms if r.status == RoomStatus.OCCUPIED])
    available_count = len([r for r in rooms if r.status == RoomStatus.AVAILABLE])
    dirty_count = len(dirty_rooms)
    ooo_count = len([r for r in rooms if r.status == RoomStatus.OUT_OF_ORDER])
    reserved_count = len([r for r in rooms if r.status == RoomStatus.RESERVED])
    occupancy_pct = flt((occupied_count / total_rooms) * 100, 1) if total_rooms > 0 else 0.0

    ota_bookings_count = frappe.db.count("OTA Reservation", {"status": "New"})

    kpis = {
        "ota_bookings": ota_bookings_count,
        "arrivals": len(arrivals),
        "departures": len(departures),
        "in_house": len(in_house),
        "available": available_count,
        "dirty": dirty_count,
        "ooo": ooo_count,
        "reserved": reserved_count,
        "occupancy_pct": occupancy_pct,
        "occupied": occupied_count,
        "total_rooms": total_rooms
    }

    return {
        "target_date": target_date,
        "kpis": kpis,
        "hotel_name": settings.get("hotel_name") or company,
        "rooms": rooms,
        "arrivals": arrivals,
        "departures": departures,
        "in_house": in_house,
        "dirty": dirty_rooms,
        "maintenance": maintenance_issues,
        "floors": sorted({r.floor for r in rooms if r.floor}, key=lambda x: str(x)),
        "room_types": sorted({r.room_type for r in rooms if r.room_type}),
        "setup_warnings": get_setup_warnings(settings, total_rooms),
        "can_setup": "System Manager" in frappe.get_roles() or frappe.session.user == "Administrator",
        "ota_bookings_count": ota_bookings_count,
        "settings": {
            "company": company,
            "restaurant_pos_profile": settings.restaurant_pos_profile,
            "room_pos_profile": settings.room_pos_profile,
            "default_advance_mode": settings.default_advance_mode or "Cash",
            "console_refresh_seconds": settings.console_refresh_seconds or 60
        }
    }


@frappe.whitelist()
def search(text):
    """Global search across guests, rooms, and reservations."""
    require_console_access()
    if not text or len(text.strip()) < 2:
        return []

    q = f"%{text.strip()}%"
    results = []

    # Search Rooms
    rooms = frappe.db.sql("""
        SELECT name, room_number, room_type, status, current_reservation
        FROM `tabHotel Room`
        WHERE room_number LIKE %s OR name LIKE %s
        LIMIT 5
    """, (q, q), as_dict=True)
    for r in rooms:
        results.append({
            "type": "Room",
            "label": f"Room {r.room_number} ({r.status})",
            "value": r.name,
            "details": r.room_type,
            "doc": r
        })

    # Search Reservations
    reservations = frappe.db.sql("""
        SELECT r.name, r.customer, c.customer_name, r.room, r.status
        FROM `tabHotel Reservation` r
        LEFT JOIN `tabCustomer` c ON c.name = r.customer
        WHERE r.name LIKE %s OR r.customer LIKE %s OR c.customer_name LIKE %s
        LIMIT 5
    """, (q, q, q), as_dict=True)
    for res in reservations:
        results.append({
            "type": "Reservation",
            "label": f"{res.name} · {res.customer_name or res.customer} (Room {res.room or 'Unassigned'})",
            "value": res.name,
            "details": res.status,
            "doc": res
        })

    # Search Guests
    customers = frappe.db.sql("""
        SELECT name, customer_name, guest_id_number, mobile_no
        FROM `tabCustomer`
        WHERE is_hotel_guest = 1 AND (customer_name LIKE %s OR name LIKE %s OR mobile_no LIKE %s)
        LIMIT 5
    """, (q, q, q), as_dict=True)
    for c in customers:
        c.guest_id_number = mask_id(c.guest_id_number)
        results.append({
            "type": "Guest",
            "label": f"Guest: {c.customer_name or c.name}",
            "value": c.name,
            "details": c.mobile_no or "",
            "doc": c
        })

    return results


@frappe.whitelist()
def get_available_rooms(room_type, check_in_date, check_out_date, exclude_reservation=None):
    require_console_access()
    rooms = v1_get_available_rooms(room_type, check_in_date, check_out_date, exclude_reservation)
    rate = get_room_rate(room_type, check_in_date)
    for r in rooms:
        r["rate"] = rate
    return rooms


@frappe.whitelist()
def get_room_type_availability(room_type, check_in_date, check_out_date, exclude_reservation=None):
    """Room-type inventory for a date range (no physical room is reserved by a booking)."""
    require_console_access()
    out = v1_room_type_availability(room_type, check_in_date, check_out_date, exclude_reservation)
    out["rate"] = get_room_rate(room_type, check_in_date)
    out["nights"] = date_diff(check_out_date, check_in_date)
    return out


@frappe.whitelist()
def create_reservation(data, advance=None):
    """Front-desk booking: holds room-type inventory only. The physical room is chosen at check-in."""
    require_console_access()
    if isinstance(data, str):
        data = frappe.parse_json(data)
    if isinstance(advance, str) and advance:
        advance = frappe.parse_json(advance)
    return _create_reservation(data, advance)


def _create_reservation(data, advance=None):
    if not data.get("room_type"):
        frappe.throw(_("Select a room type."))
    validate_reservation_dates(data.get("check_in_date"), data.get("check_out_date"))
    validate_guest_capacity(data.get("room_type"), data.get("adults") or 1, data.get("children") or 0)

    # 1. Inline Guest Creation if needed (no identity data is collected at booking)
    customer = data.get("customer")
    guest_name = (data.get("guest_name") or "").strip()
    if not customer and guest_name:
        cust_doc = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": guest_name,
            "customer_type": "Individual",
            "is_hotel_guest": 1,
            "mobile_no": data.get("mobile_no"),
            "customer_group": get_settings().guest_customer_group or None,
            "territory": get_settings().guest_territory or None,
        })
        cust_doc.insert(ignore_permissions=True)
        customer = cust_doc.name

    if not customer:
        frappe.throw(_("Select an existing guest or enter a new guest name."))
    allowed = ("room_type", "check_in_date", "check_out_date", "adults", "children", "remarks", "rate_plan")
    res_data = {k: data.get(k) for k in allowed if data.get(k) not in (None, "")}
    res_data.update({"doctype": "Hotel Reservation", "customer": customer, "status": ReservationStatus.RESERVED})
    res_data.setdefault("adults", 1)
    res_doc = frappe.get_doc(res_data)
    res_doc.insert(ignore_permissions=True)

    # 2. Advance Payment if provided
    payment_entry_name = None
    if advance and flt(advance.get("amount")) > 0:
        company = res_doc.company or get_company()
        company_doc = frappe.get_doc("Company", company)
        mode = advance.get("mode") or get_settings().default_advance_mode or "Cash"
        from hospitality_core.integrations.razorpay.guards import gateway_mode_of_payment
        if mode == gateway_mode_of_payment():
            frappe.throw(_("Online (Razorpay) advances are collected from the reservation's Receive Payment dialog after it is created."))
        paid_to = frappe.db.get_value("Mode of Payment Account", {"parent": mode, "company": company}, "default_account") or company_doc.default_cash_account
        paid_from = company_doc.default_receivable_account

        pe = frappe.get_doc({
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": customer,
            "company": company,
            "hotel_reservation": res_doc.name,
            "mode_of_payment": mode,
            "paid_to": paid_to,
            "paid_from": paid_from,
            "paid_amount": flt(advance.get("amount")),
            "received_amount": flt(advance.get("amount")),
            "reference_no": advance.get("reference_no")
        })
        pe.insert(ignore_permissions=True)
        pe.submit()
        payment_entry_name = pe.name

    billing = get_billing_summary(res_doc.name)
    emit_console_update("reservation_created", {"reservation": res_doc.name, "room": res_doc.room})

    return {
        "reservation": _safe_reservation(res_doc),
        "billing": billing,
        "payment_entry": payment_entry_name
    }


@frappe.whitelist()
def walk_in(data, advance=None):
    """Creates a reservation and immediately checks in the guest in one step."""
    require_console_access()
    if isinstance(data, str):
        data = frappe.parse_json(data)

    if isinstance(advance, str) and advance:
        advance = frappe.parse_json(advance)
    if not data.get("room"):
        frappe.throw(_("Select a room for the walk-in guest."))

    data["check_in_date"] = nowdate()
    res_out = _create_reservation(data, advance)
    res_name = res_out["reservation"]["name"]

    # Check in: identity verification + physical room allocation
    v1_check_in(res_name, room=data.get("room"), guest_id_type=data.get("guest_id_type"),
                guest_id_number=data.get("guest_id_number"), guest_id_document=data.get("guest_id_document"))
    res_doc = frappe.get_doc("Hotel Reservation", res_name)
    emit_console_update("walk_in_completed", {"reservation": res_name, "room": res_doc.room})

    return {
        "reservation": _safe_reservation(res_doc),
        "billing": get_billing_summary(res_name)
    }


def _safe_reservation(doc):
    """Reservation dict for the browser, with identity data masked."""
    d = doc.as_dict()
    d["guest_id_number"] = mask_id(d.get("guest_id_number"))
    d.pop("guest_id_document", None)
    return d


@frappe.whitelist()
def get_checkin_details(reservation_name):
    """Everything the check-in modal needs: guest/stay summary and the rooms that can be allocated."""
    require_console_access()
    res = frappe.get_doc("Hotel Reservation", reservation_name)
    if res.status != ReservationStatus.RESERVED:
        frappe.throw(_("Only Reserved bookings can be checked in."))
    guest = frappe.db.get_value("Customer", res.customer, ["customer_name", "mobile_no"], as_dict=True) or {}
    settings = get_settings()
    return {
        "reservation": {
            "name": res.name, "customer": res.customer, "guest_name": guest.get("customer_name") or res.customer,
            "mobile_no": guest.get("mobile_no"), "room_type": res.room_type, "room": res.room,
            "check_in_date": res.check_in_date, "check_out_date": res.check_out_date,
            "adults": res.adults, "children": res.children,
        },
        "rooms": v1_physical_rooms(res.name),
        "require_id": bool(settings.get("require_guest_id_at_checkin")),
    }


@frappe.whitelist(methods=["POST"])
def check_in(reservation_name, room=None, guest_id_type=None, guest_id_number=None, guest_id_document=None):
    require_console_access()
    v1_check_in(reservation_name, room=room, guest_id_type=guest_id_type,
                guest_id_number=guest_id_number, guest_id_document=guest_id_document)
    res_doc = frappe.get_doc("Hotel Reservation", reservation_name)
    emit_console_update("check_in", {"reservation": reservation_name, "room": res_doc.room})
    return {"status": "success", "reservation": _safe_reservation(res_doc)}


@frappe.whitelist()
def move_room(reservation_name, new_room, reason=None, keep_rate=0):
    require_console_access()
    res = v1_move_room(reservation_name, new_room, reason, keep_rate)
    res_doc = frappe.get_doc("Hotel Reservation", reservation_name)
    emit_console_update("move_room", {"reservation": reservation_name, "new_room": new_room})
    return {"status": "success", "reservation": _safe_reservation(res_doc)}


@frappe.whitelist()
def cancel_reservation(reservation_name, reason=None):
    require_console_access()
    res = v1_cancel_reservation(reservation_name)
    emit_console_update("cancel_reservation", {"reservation": reservation_name})
    return {"status": "success"}


@frappe.whitelist()
def extend_stay(reservation_name, new_check_out_date):
    require_console_access()
    from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import get_conflicting_reservation
    frappe.db.get_value("Hotel Reservation", reservation_name, "status", for_update=True)
    res = frappe.get_doc("Hotel Reservation", reservation_name)
    if res.status not in (ReservationStatus.RESERVED, ReservationStatus.CHECKED_IN):
        frappe.throw(_("Only Reserved or Checked In stays can be changed."))
    new_date = getdate(new_check_out_date)
    if new_date <= getdate(res.check_in_date):
        frappe.throw(_("New check out date must be after check in date."))
    if res.status == ReservationStatus.CHECKED_IN and new_date < getdate(nowdate()):
        frappe.throw(_("New check out date cannot be in the past."))
    old_date = getdate(res.check_out_date)
    if new_date > old_date and res.room:
        conflict = get_conflicting_reservation(res.room, old_date, new_date, exclude=res.name)
        if conflict:
            frappe.throw(_("Room {0} is booked by {1} in the extended period. Move the guest or choose another date.").format(res.room, conflict))

    res.check_out_date = new_date
    res.save(ignore_permissions=True)
    billing = get_billing_summary(res.name)
    emit_console_update("extend_stay", {"reservation": reservation_name})
    return {"status": "success", "reservation": _safe_reservation(res), "billing": billing}


@frappe.whitelist()
def get_bill_preview(reservation_name):
    require_console_access()
    from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import build_sales_invoice
    inv = build_sales_invoice(reservation_name)
    billing = get_billing_summary(reservation_name)

    items = []
    for item in inv.items:
        items.append({
            "item_code": item.item_code,
            "item_name": item.item_name,
            "description": item.description,
            "qty": item.qty,
            "rate": item.rate,
            "amount": item.amount,
            "discount_percentage": item.discount_percentage,
            "source": item.hotel_source_invoice or "Room Night"
        })

    return {
        "reservation": reservation_name,
        "items": items,
        "taxes": [{"description": t.description, "tax_amount": t.tax_amount} for t in inv.taxes],
        "grand_total": inv.grand_total,
        "total_paid": billing["total_paid"],
        "balance": billing["balance"],
        "room_service_pending": billing.get("room_service_pending", 0.0),
        "room_service_paid": billing.get("room_service_paid", 0.0)
    }


@frappe.whitelist()
def receive_payment(reservation_name, mode, amount, reference=None):
    require_console_access()
    res = frappe.get_doc("Hotel Reservation", reservation_name)
    if flt(amount) <= 0:
        frappe.throw(_("Payment amount must be greater than zero."))
    if res.status not in (ReservationStatus.RESERVED, ReservationStatus.CHECKED_IN):
        frappe.throw(_("Payments can only be received for Reserved or Checked In stays (reservation is {0}).").format(res.status))
    if not mode:
        frappe.throw(_("Mode of Payment is required."))
    from hospitality_core.integrations.razorpay.guards import gateway_mode_of_payment
    if mode == gateway_mode_of_payment():
        frappe.throw(_("Use 'Collect Online (Razorpay)' for online payments. They are recorded only after verification."))
    company = res.company or get_company()
    company_doc = frappe.get_doc("Company", company)

    paid_to = frappe.db.get_value("Mode of Payment Account", {"parent": mode, "company": company}, "default_account") or company_doc.default_cash_account
    paid_from = company_doc.default_receivable_account

    pe = frappe.get_doc({
        "doctype": "Payment Entry",
        "payment_type": "Receive",
        "party_type": "Customer",
        "party": res.customer,
        "company": company,
        "hotel_reservation": res.name,
        "mode_of_payment": mode,
        "paid_to": paid_to,
        "paid_from": paid_from,
        "paid_amount": flt(amount),
        "received_amount": flt(amount),
        "reference_no": reference
    })
    pe.insert(ignore_permissions=True)
    pe.submit()

    billing = get_billing_summary(reservation_name)
    emit_console_update("payment_received", {"reservation": reservation_name, "amount": amount})

    return {
        "status": "success",
        "payment_entry": pe.name,
        "billing": billing
    }


@frappe.whitelist()
def check_out(reservation_name, collect_payment=None):
    require_console_access()
    if collect_payment and isinstance(collect_payment, str):
        collect_payment = frappe.parse_json(collect_payment)

    if collect_payment and flt(collect_payment.get("amount")) > 0:
        receive_payment(
            reservation_name,
            collect_payment.get("mode"),
            collect_payment.get("amount"),
            collect_payment.get("reference")
        )

    res = v1_check_out(reservation_name)
    emit_console_update("checkout_completed", {"reservation": reservation_name})

    print_url = f"/api/method/frappe.utils.print_format.download_pdf?doctype=Sales Invoice&name={res['sales_invoice']}&format=Standard"

    return {
        "status": "success",
        "sales_invoice": res["sales_invoice"],
        "print_url": print_url
    }


@frappe.whitelist()
def report_issue(room, subject, priority="Medium", description=None):
    require_console_access()
    issue = frappe.get_doc({
        "doctype": "Issue",
        "subject": subject,
        "hotel_room": room,
        "priority": priority,
        "description": description or subject,
        "status": "Open"
    })
    issue.insert(ignore_permissions=True)
    emit_console_update("issue_reported", {"room": room, "issue": issue.name})
    return {"status": "success", "issue": issue.name}


@frappe.whitelist()
def resolve_issue(issue_name, notes=None):
    require_console_access()
    issue = frappe.get_doc("Issue", issue_name)
    issue.status = "Resolved"
    if notes:
        issue.add_comment("Comment", f"Resolution: {notes}")
    issue.save(ignore_permissions=True)
    emit_console_update("issue_resolved", {"room": issue.hotel_room, "issue": issue.name})
    return {"status": "success", "room": issue.hotel_room}


@frappe.whitelist()
def set_housekeeping(room_number, action):
    require_console_access()
    from hospitality_core.hospitality_core.page.housekeeping_view.housekeeping_view import toggle_room_status
    res = toggle_room_status(room_number, "mark_clean" if action == "Clean" else "mark_dirty")
    emit_console_update("housekeeping_updated", {"room": room_number, "status": res["status"]})
    return res


@frappe.whitelist()
def ensure_pos_opening(pos_profile):
    """
    Returns an active POS Opening Entry for (user, pos_profile).
    If none exists, automatically creates one with zero balances so cashier is never blocked.
    """
    require_console_access()
    user = frappe.session.user
    today = nowdate()

    open_entry = frappe.db.get_value(
        "POS Opening Entry",
        {
            "user": user,
            "pos_profile": pos_profile,
            "status": "Open",
            "docstatus": 1
        },
        "name"
    )

    if open_entry:
        return {"name": open_entry, "status": "Open"}

    # Create new POS Opening Entry
    pos_prof_doc = frappe.get_doc("POS Profile", pos_profile)
    company = pos_prof_doc.company

    balances = []
    for p in pos_prof_doc.payments:
        balances.append({
            "mode_of_payment": p.mode_of_payment,
            "opening_amount": 0.0
        })

    opening_doc = frappe.get_doc({
        "doctype": "POS Opening Entry",
        "period_start_date": now_datetime(),
        "posting_date": today,
        "company": company,
        "pos_profile": pos_profile,
        "user": user,
        "balance_details": balances
    })
    opening_doc.insert(ignore_permissions=True)
    opening_doc.submit()

    return {"name": opening_doc.name, "status": "Created"}



def get_setup_warnings(settings, total_rooms):
    w = []
    if not total_rooms:
        w.append(_("No hotel rooms exist yet. Create Room Types and Rooms to start."))
    if not settings.company:
        w.append(_("Company is not set in Hotel Settings."))
    if not settings.default_room_item:
        w.append(_("Default Room Item is not set in Hotel Settings (needed for billing)."))
    if not settings.restaurant_pos_profile:
        w.append(_("Restaurant POS Profile is not set in Hotel Settings."))
    if not settings.room_pos_profile:
        w.append(_("Room Service POS Profile is not set in Hotel Settings."))
    return w


def _payments_for(reservation_name):
    return frappe.get_all(
        "Payment Entry",
        filters={"hotel_reservation": reservation_name, "docstatus": 1, "payment_type": "Receive"},
        fields=["name", "posting_date", "mode_of_payment", "paid_amount", "reference_no"],
        order_by="posting_date asc, creation asc",
    )


@frappe.whitelist()
def get_reservation_details(reservation_name):
    """Everything the room/reservation modal needs in one call."""
    require_console_access()
    res = frappe.get_doc("Hotel Reservation", reservation_name)
    cust = frappe.db.get_value(
        "Customer", res.customer, ["customer_name", "mobile_no", "email_id"], as_dict=True
    ) or {}
    cust["guest_id_type"] = res.get("guest_id_type")
    cust["guest_id_number"] = mask_id(res.get("guest_id_number"))
    cust["id_document_attached"] = bool(res.get("guest_id_document"))
    billing = get_billing_summary(res.name) if res.status != ReservationStatus.CANCELLED else {}
    room_orders = frappe.get_all(
        "Sales Invoice",
        filters={"hotel_reservation": res.name, "hotel_order_type": "Room Service", "docstatus": ["<", 2]},
        fields=["name", "posting_date", "grand_total", "docstatus", "charge_to_room"],
        order_by="creation asc",
    )
    return {
        "reservation": {
            "name": res.name, "status": res.status, "customer": res.customer,
            "room": res.room, "room_type": res.room_type,
            "check_in_date": res.check_in_date, "check_out_date": res.check_out_date,
            "adults": res.adults, "children": res.children, "remarks": res.remarks,
            "sales_invoice": res.sales_invoice,
            "nights": max(date_diff(res.check_out_date, res.check_in_date), 1),
            "rate": res.stays[-1].rate if res.stays else 0,
        },
        "guest": cust,
        "stays": [
            {"room": s.room, "room_type": s.room_type, "from_date": s.from_date,
             "to_date": s.to_date, "rate": s.rate, "nights": s.nights}
            for s in res.stays
        ],
        "payments": _payments_for(res.name),
        "room_orders": room_orders,
        "billing": billing,
    }


@frappe.whitelist()
def get_reservations(status=None, text=None, from_date=None, to_date=None, limit=100):
    require_console_access()
    cond, vals = ["1=1"], {}
    if status == "Upcoming":
        cond.append("r.status = 'Reserved' AND r.check_in_date >= %(today)s")
        vals["today"] = nowdate()
    elif status:
        cond.append("r.status = %(status)s")
        vals["status"] = status
    if text:
        cond.append("(r.name LIKE %(t)s OR c.customer_name LIKE %(t)s OR r.room LIKE %(t)s)")
        vals["t"] = f"%{text}%"
    if from_date:
        cond.append("r.check_out_date >= %(fd)s")
        vals["fd"] = from_date
    if to_date:
        cond.append("r.check_in_date <= %(td)s")
        vals["td"] = to_date
    vals["limit"] = min(int(limit or 100), 500)
    return frappe.db.sql(f"""
        SELECT r.name, r.customer, c.customer_name AS guest_name, r.room, r.room_type,
               r.check_in_date, r.check_out_date, r.status, r.balance, r.estimated_total
        FROM `tabHotel Reservation` r
        LEFT JOIN `tabCustomer` c ON c.name = r.customer
        WHERE {" AND ".join(cond)}
        ORDER BY r.check_in_date DESC, r.creation DESC
        LIMIT %(limit)s
    """, vals, as_dict=True)


@frappe.whitelist()
def change_reserved_room(reservation_name, new_room):
    """Reassign the room of a not-yet-arrived (Reserved) booking."""
    require_console_access()
    frappe.db.get_value("Hotel Reservation", reservation_name, "status", for_update=True)
    res = frappe.get_doc("Hotel Reservation", reservation_name)
    if res.status != ReservationStatus.RESERVED:
        frappe.throw(_("Only Reserved bookings can change room here. Use Move Room for in-house guests."))
    new_type = frappe.db.get_value("Hotel Room", new_room, "room_type")
    res.room = new_room
    if new_type != res.room_type:
        res.room_type = new_type
        if len(res.stays) == 1:
            res.stays[0].rate = get_room_rate(new_type, res.check_in_date, res.customer)
    res.save(ignore_permissions=True)
    emit_console_update("room_changed", {"reservation": res.name, "room": new_room})
    return {"status": "success"}


@frappe.whitelist()
def get_in_house_for_pos():
    require_console_access()
    from hospitality_core.pos import get_in_house_guests
    return get_in_house_guests()


@frappe.whitelist()
def create_sample_rooms():
    """One-click starter data (System Manager only): 2 room types, 6 rooms. Idempotent."""
    frappe.only_for("System Manager")
    from hospitality_core.utils import ensure_default_room_item
    item = ensure_default_room_item()
    created = []
    for rt, rate, floor_rooms in (("Standard", 2500, ("101", "102", "103")), ("Deluxe", 4000, ("201", "202", "203"))):
        if not frappe.db.exists("Hotel Room Type", rt):
            frappe.get_doc({"doctype": "Hotel Room Type", "room_type_name": rt, "default_rate": rate,
                            "item": item, "max_adults": 2}).insert(ignore_permissions=True)
        for num in floor_rooms:
            if not frappe.db.exists("Hotel Room", num):
                frappe.get_doc({"doctype": "Hotel Room", "room_number": num, "room_type": rt,
                                "floor": num[0], "status": "Available", "is_enabled": 1}).insert(ignore_permissions=True)
                created.append(num)
    return {"created": created}


@frappe.whitelist()
def get_ota_bookings(status=None, text=None, limit=100):
    require_console_access()
    filters = {}
    if status and status != "All":
        filters["status"] = status

    or_filters = []
    if text:
        or_filters = [
            ["guest_name", "like", f"%{text}%"],
            ["ota_booking_id", "like", f"%{text}%"],
            ["channel_name", "like", f"%{text}%"],
            ["room_type_name", "like", f"%{text}%"],
        ]

    fields = [
        "name", "ota_booking_id", "channel_name", "status", "guest_name",
        "guest_phone", "guest_email", "check_in_date", "check_out_date",
        "nights", "room_type_name", "rate_plan_name", "total_amount",
        "currency", "payment_status", "received_at"
    ]

    return frappe.get_all(
        "OTA Reservation",
        filters=filters,
        or_filters=or_filters if or_filters else None,
        fields=fields,
        order_by="received_at desc, creation desc",
        limit=limit
    )
