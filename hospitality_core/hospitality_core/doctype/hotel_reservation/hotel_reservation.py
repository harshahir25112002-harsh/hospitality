import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, getdate, now_datetime, date_diff, flt
from hospitality_core.constants import RoomStatus, ReservationStatus
from hospitality_core.room_status import set_room_status
from hospitality_core.utils import get_settings, get_company, get_room_item

ACTIVE_STATUSES = (ReservationStatus.RESERVED, ReservationStatus.CHECKED_IN)
ID_TYPES = ("Aadhaar", "PAN", "Driving Licence", "Passport", "Voter ID", "Other")
ALNUM_ID = re.compile(r"^[A-Z0-9/-]{4,30}$")
ID_PATTERNS = {
    "Aadhaar": re.compile(r"^[0-9]{12}$"),
    "PAN": re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$"),
}
ID_DOC_EXTENSIONS = {"jpg", "jpeg", "png", "pdf", "webp"}


class RoomTypeUnavailable(frappe.ValidationError):
    http_status_code = 409


class RoomUnavailable(frappe.ValidationError):
    http_status_code = 409


class IdentityRequired(frappe.ValidationError):
    pass


def mask_id(value):
    """Show only the last 4 characters of an identity number."""
    value = (value or "").strip()
    if not value:
        return ""
    return "X" * max(len(value) - 4, 4) + value[-4:] if len(value) > 4 else "XXXX"


class HotelReservation(Document):
    def validate(self):
        if not self.company:
            self.company = get_company()

        if getdate(self.check_in_date) >= getdate(self.check_out_date):
            frappe.throw(_("Check-out date must be after check-in date."))

        # If rate is not resolved or rate_plan changed, resolve rate
        if not self.stays:
            rate = get_room_rate(self.room_type, self.check_in_date, self.customer)
            nights = max(date_diff(self.check_out_date, self.check_in_date), 1)
            self.append("stays", {
                "room": self.room,
                "room_type": self.room_type,
                "from_date": self.check_in_date,
                "to_date": self.check_out_date,
                "rate": rate,
                "nights": nights
            })
        elif len(self.stays) == 1:
            stay = self.stays[0]
            if self.room and stay.room != self.room:
                stay.room = self.room
            if self.room_type and stay.room_type != self.room_type:
                stay.room_type = self.room_type
            stay.from_date = self.check_in_date
            stay.to_date = self.check_out_date
            stay.nights = max(date_diff(self.check_out_date, self.check_in_date), 1)
        else:
            # Multi-segment stay: ensure last stay finishes on check_out_date
            last_stay = self.stays[-1]
            if getdate(last_stay.to_date) != getdate(self.check_out_date):
                last_stay.to_date = self.check_out_date
                last_stay.nights = max(date_diff(self.check_out_date, last_stay.from_date), 1)

        for s in self.stays:
            if s.to_date and getdate(s.to_date) < getdate(s.from_date):
                frappe.throw(_("Stay to_date ({0}) cannot be before from_date ({1}) for room {2}.").format(
                    s.to_date, s.from_date, s.room
                ))

        if self.status in ACTIVE_STATUSES:
            self.validate_capacity()
            if self._stay_changed():
                self.validate_room_type_inventory()
            if self.room and (self._stay_changed() or self.has_value_changed("room")):
                self.validate_room_availability()

    def on_update(self):
        if self.status == ReservationStatus.RESERVED:
            if self.room:
                old_doc = self.get_doc_before_save()
                if old_doc and old_doc.room and old_doc.room != self.room:
                    try:
                        old_room_doc = frappe.get_doc("Hotel Room", old_doc.room)
                        if old_room_doc.current_reservation == self.name:
                            set_room_status(old_doc.room, RoomStatus.AVAILABLE, reason=f"Room changed in reservation {self.name}")
                    except Exception:
                        pass
                # A future booking must not block the room today: the room is only flagged
                # Reserved on/after the arrival date (see mark_todays_arrivals scheduler).
                if getdate(self.check_in_date) <= getdate():
                    room_status = frappe.db.get_value("Hotel Room", self.room, "status")
                    if room_status in (RoomStatus.AVAILABLE, RoomStatus.RESERVED):
                        set_room_status(self.room, RoomStatus.RESERVED, reason=f"Reserved by {self.name}", reservation=self.name)
        elif self.status == ReservationStatus.CANCELLED:
            if self.room:
                try:
                    room_doc = frappe.get_doc("Hotel Room", self.room)
                    if room_doc.current_reservation == self.name:
                        set_room_status(self.room, RoomStatus.AVAILABLE, reason=f"Reservation {self.name} cancelled")
                except Exception:
                    pass

        # 2-Way Push to OTA
        try:
            from hospitality_core.api.ota import push_room_type_availability_to_ota
            push_room_type_availability_to_ota(self.room_type, self.check_in_date, self.check_out_date)
        except Exception:
            pass

    def on_trash(self):
        if self.room:
            try:
                room_doc = frappe.get_doc("Hotel Room", self.room)
                if room_doc.current_reservation == self.name:
                    set_room_status(self.room, RoomStatus.AVAILABLE, reason=f"Reservation {self.name} deleted")
            except Exception:
                pass

        # 2-Way Push to OTA
        try:
            from hospitality_core.api.ota import push_room_type_availability_to_ota
            push_room_type_availability_to_ota(self.room_type, self.check_in_date, self.check_out_date)
        except Exception:
            pass

    def _stay_changed(self):
        """New booking, re-activated booking, or a change of room type / dates."""
        old = self.get_doc_before_save()
        if self.is_new() or not old:
            return True
        if old.status not in ACTIVE_STATUSES:
            return True
        return (old.room_type != self.room_type
                or getdate(old.check_in_date) != getdate(self.check_in_date)
                or getdate(old.check_out_date) != getdate(self.check_out_date))

    def validate_capacity(self):
        if (
            getattr(self.flags, "ignore_validate_capacity", False)
            or self.ota_reservation
            or self.status in (ReservationStatus.CHECKED_IN, ReservationStatus.CHECKED_OUT)
        ):
            return
        validate_guest_capacity(self.room_type, self.adults, self.children)

    def validate_room_type_inventory(self):
        """Room-type inventory: never let overlapping active bookings exceed eligible rooms on any night."""
        if getattr(self.flags, "ignore_validate_inventory", False) or self.ota_reservation:
            return
        if self.room_type and not frappe.db.exists("Hotel Room Type", self.room_type):
            frappe.throw(_("Room Type {0} does not exist.").format(self.room_type))
        # In-house guests already hold a physical room; only pre-arrival bookings consume free inventory.
        if self.status != ReservationStatus.RESERVED:
            return
        avail = get_room_type_availability(self.room_type, self.check_in_date, self.check_out_date,
                                           exclude_reservation=self.name, for_update=True)
        if avail["available"] < 1:
            frappe.throw(_("No {0} rooms are available from {1} to {2}.").format(
                self.room_type, self.check_in_date, self.check_out_date), RoomTypeUnavailable)

    def validate_room_availability(self):
        """
        Validate that self.room is available for [check_in_date, check_out_date).
        """
        if not self.room:
            return

        frappe.db.get_value("Hotel Room", self.room, "status", for_update=True)
        room_doc = frappe.get_doc("Hotel Room", self.room)
        if not room_doc.is_enabled:
            frappe.throw(_("Room {0} is disabled.").format(self.room))
        if self.room_type and room_doc.room_type != self.room_type:
            frappe.throw(_("Room {0} is a {1}, not a {2}.").format(self.room, room_doc.room_type, self.room_type))

        # Physical room state only matters for a stay that starts now (walk-in / same-day arrival).
        # Housekeeping and maintenance are resolved before a future arrival.
        if getdate(self.check_in_date) <= getdate():
            if room_doc.status == RoomStatus.OUT_OF_ORDER:
                frappe.throw(_("Room {0} is currently Out of Order.").format(self.room))
            if room_doc.status == RoomStatus.OCCUPIED and room_doc.current_reservation != self.name:
                frappe.throw(_("Room {0} is currently Occupied.").format(self.room))

        # Check overlapping reservations (check-in inclusive, check-out exclusive)
        conflict = get_conflicting_reservation(self.room, self.check_in_date, self.check_out_date, exclude=self.name)
        if conflict:
            frappe.throw(_("Room {0} is already booked by reservation {1} for the requested dates.").format(
                self.room, conflict), RoomUnavailable)


@frappe.whitelist()
def get_available_rooms(room_type, check_in_date, check_out_date, exclude_reservation=None):
    if getdate(check_in_date) >= getdate(check_out_date):
        frappe.throw(_("Check-out date must be after check-in date."))

    all_rooms = frappe.get_all(
        "Hotel Room",
        filters={"room_type": room_type, "is_enabled": 1},
        fields=["name", "room_number", "status", "floor", "current_reservation"]
    )

    # Exclude currently Out of Order, Dirty, Occupied, and Reserved rooms from selection
    starts_now = getdate(check_in_date) <= getdate()

    def is_room_selectable(r):
        # Future stays: only date overlap matters (checked below).
        if not starts_now:
            return True
        if r.status in (RoomStatus.OUT_OF_ORDER, RoomStatus.OCCUPIED):
            return r.status == RoomStatus.OCCUPIED and exclude_reservation and r.current_reservation == exclude_reservation
        return True

    all_rooms = [r for r in all_rooms if is_room_selectable(r)]

    booked_rooms = frappe.db.sql("""
        SELECT DISTINCT COALESCE(s.room, r.room) as room
        FROM `tabHotel Reservation` r
        LEFT JOIN `tabHotel Reservation Stay` s ON s.parent = r.name AND s.parenttype = 'Hotel Reservation'
        WHERE r.status IN ('Reserved', 'Checked In')
        AND r.name != %(exclude_res)s
        AND COALESCE(s.from_date, r.check_in_date) < %(check_out)s
        AND COALESCE(s.to_date, r.check_out_date) > %(check_in)s
    """, {
        "exclude_res": exclude_reservation or "",
        "check_in": check_in_date,
        "check_out": check_out_date
    }, as_dict=True)

    booked_room_names = {b.room for b in booked_rooms if b.room}
    return [r for r in all_rooms if r.name not in booked_room_names]


@frappe.whitelist()
def get_room_rate(room_type, date, customer=None):
    customer_group = None
    if customer:
        customer_group = frappe.db.get_value("Customer", customer, "customer_group")

    date = getdate(date)

    if customer:
        plan = frappe.db.get_value(
            "Room Rate Plan",
            {
                "room_type": room_type,
                "customer": customer,
                "active": 1,
                "valid_from": ["<=", date],
                "valid_to": [">=", date]
            },
            "rate"
        )
        if plan:
            return flt(plan)

    if customer_group:
        plan = frappe.db.get_value(
            "Room Rate Plan",
            {
                "room_type": room_type,
                "customer_group": customer_group,
                "active": 1,
                "valid_from": ["<=", date],
                "valid_to": [">=", date]
            },
            "rate"
        )
        if plan:
            return flt(plan)

    plan = frappe.db.sql("""
        SELECT rate FROM `tabRoom Rate Plan`
        WHERE room_type = %s
        AND active = 1
        AND (customer IS NULL OR customer = '')
        AND (customer_group IS NULL OR customer_group = '')
        AND valid_from <= %s AND valid_to >= %s
        ORDER BY rate ASC LIMIT 1
    """, (room_type, date, date), as_dict=True)
    if plan:
        return flt(plan[0].rate)

    default_rate = frappe.db.get_value("Hotel Room Type", room_type, "default_rate")
    return flt(default_rate or 0.0)


@frappe.whitelist()
def check_in(reservation_name, room=None, guest_id_type=None, guest_id_number=None, guest_id_document=None):
    """Check-in = identity verification + physical room allocation + status change, in one transaction.
    Row locks on the reservation and the chosen room make a concurrent second allocation fail cleanly."""
    frappe.db.get_value("Hotel Reservation", reservation_name, "status", for_update=True)
    res = frappe.get_doc("Hotel Reservation", reservation_name)
    res.check_permission("write")
    if res.status != ReservationStatus.RESERVED:
        frappe.throw(_("Only reservations in 'Reserved' status can be checked in."))

    settings = get_settings()
    today = getdate()
    if getdate(res.check_in_date) > today and not settings.allow_checkin_before_arrival:
        frappe.throw(_("Check-in before arrival date ({0}) is not allowed by Hotel Settings.").format(res.check_in_date))
    identity = validate_identity(guest_id_type, guest_id_number, guest_id_document, settings, res.name)

    room = room or res.room
    if not room:
        frappe.throw(_("Select a physical room to check the guest in."))
    validate_room_assignment(res, room, today)

    if res.stays:
        res.stays[0].from_date = today
        if getdate(res.stays[0].to_date) <= today:
            res.stays[0].to_date = frappe.utils.add_days(today, 1)
        res.stays[0].nights = max(date_diff(res.stays[0].to_date, res.stays[0].from_date), 1)
        res.check_out_date = res.stays[-1].to_date
        for st in res.stays:
            if not st.room:
                st.room = room

    res.room = room
    res.status = ReservationStatus.CHECKED_IN
    res.checked_in_on = now_datetime()
    res.flags.ignore_validate_capacity = True
    res.flags.ignore_validate_inventory = True
    res.save()

    # Identity data is written outside document versioning so it never lands in Version history.
    identity["id_verified_by"] = frappe.session.user
    frappe.db.set_value("Hotel Reservation", res.name, identity, update_modified=False)
    if identity.get("guest_id_document"):
        _attach_id_document(identity["guest_id_document"], res.name)

    set_room_status(room, RoomStatus.OCCUPIED, reason=f"Check-in {res.name}", reservation=res.name)
    return {"status": res.status, "room": room}


def validate_identity(id_type, id_number, id_document, settings, reservation_name=None):
    id_type = (id_type or "").strip()
    id_number = re.sub(r"\s+", "", id_number or "").upper()
    if id_type and id_type not in ID_TYPES:
        frappe.throw(_("Invalid ID type."))
    if cint(settings.get("require_guest_id_at_checkin")) and (not id_type or not id_number):
        frappe.throw(_("Guest ID type and ID number are required for check-in."), IdentityRequired)
    if id_number:
        if not id_type:
            frappe.throw(_("Select the ID type."))
        pattern = ID_PATTERNS.get(id_type)
        if not ALNUM_ID.match(id_number) or (pattern and not pattern.match(id_number)):
            frappe.throw(_("The {0} number entered is not valid.").format(id_type))
    if id_document:
        _validate_id_document(id_document, reservation_name)
    out = {"guest_id_type": id_type or None, "guest_id_number": id_number or None}
    if id_document:
        out["guest_id_document"] = id_document
    return out


def _validate_id_document(file_url, reservation_name=None):
    if not isinstance(file_url, str) or not file_url.startswith("/private/files/"):
        frappe.throw(_("ID documents must be uploaded as private files."))
    ext = file_url.rsplit(".", 1)[-1].lower() if "." in file_url else ""
    if ext not in ID_DOC_EXTENSIONS:
        frappe.throw(_("ID document must be one of: {0}").format(", ".join(sorted(ID_DOC_EXTENSIONS))))
    f = frappe.db.get_value("File", {"file_url": file_url}, ["name", "owner", "attached_to_name"], as_dict=True)
    if not f:
        frappe.throw(_("Uploaded ID document not found."))
    if f.owner != frappe.session.user and f.attached_to_name != reservation_name:
        frappe.throw(_("You can only attach ID documents you uploaded."), frappe.PermissionError)


def _attach_id_document(file_url, reservation_name):
    name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if name:
        frappe.db.set_value("File", name, {"attached_to_doctype": "Hotel Reservation", "attached_to_name": reservation_name,
                                           "attached_to_field": "guest_id_document", "is_private": 1})


def validate_room_assignment(res, room, today=None):
    """Server-side check that `room` can take this reservation right now (locks the room row)."""
    today = getdate(today) if today else getdate()
    row = frappe.db.get_value("Hotel Room", room, ["name", "room_type", "status", "is_enabled", "current_reservation"],
                              as_dict=True, for_update=True)
    if not row:
        frappe.throw(_("Room {0} does not exist.").format(room))
    if not row.is_enabled:
        frappe.throw(_("Room {0} is disabled.").format(room))
    if row.room_type != res.room_type:
        frappe.throw(_("Room {0} is a {1}; this reservation is for {2}.").format(room, row.room_type, res.room_type), RoomUnavailable)
    if row.status == RoomStatus.OUT_OF_ORDER:
        frappe.throw(_("Room {0} is Out of Order.").format(room), RoomUnavailable)
    if row.status == RoomStatus.OCCUPIED:
        frappe.throw(_("Room {0} was just taken by another check-in. Please choose another room.").format(room), RoomUnavailable)
    if row.status == RoomStatus.DIRTY:
        frappe.throw(_("Room {0} is Dirty and must be cleaned before check-in.").format(room), RoomUnavailable)
    if row.status == RoomStatus.RESERVED and row.current_reservation and row.current_reservation != res.name:
        frappe.throw(_("Room {0} is held for reservation {1}.").format(room, row.current_reservation), RoomUnavailable)
    # Capacity is validated at reservation booking; do not hard-block front-desk check-in for confirmed guests
    start = min(getdate(res.check_in_date), today)
    conflict = get_conflicting_reservation(room, start, res.check_out_date, exclude=res.name)
    if conflict:
        frappe.throw(_("Room {0} is assigned to reservation {1} for overlapping dates.").format(room, conflict), RoomUnavailable)


@frappe.whitelist()
def get_available_physical_rooms(reservation_name):
    """Rooms of the reservation's type that can be allocated at check-in now."""
    res = frappe.get_doc("Hotel Reservation", reservation_name)
    res.check_permission("read")
    today = getdate()
    start = min(getdate(res.check_in_date), today)
    end = res.check_out_date if getdate(res.check_out_date) > start else frappe.utils.add_days(start, 1)
    rooms = get_available_rooms(res.room_type, start, end, exclude_reservation=res.name)
    out = []
    for r in rooms:
        if r.status == RoomStatus.AVAILABLE or (r.status == RoomStatus.RESERVED and r.current_reservation in (None, "", res.name)):
            out.append({"name": r.name, "room_number": r.room_number, "floor": r.floor, "status": r.status})
    return out


def validate_guest_capacity(room_type, adults, children):
    if not room_type:
        return
    rt = frappe.db.get_value("Hotel Room Type", room_type, ["max_adults", "max_children", "max_occupancy"], as_dict=True)
    if not rt:
        frappe.throw(_("Room Type {0} does not exist.").format(room_type))
    adults, children = cint(adults), cint(children)
    if adults < 1:
        frappe.throw(_("At least one adult is required."))
    if children < 0:
        frappe.throw(_("Children cannot be negative."))

    # Inferred capacity: Double/Twin allows at least 2 adults, Family/Suite allows 4 adults
    max_adults = cint(rt.max_adults)
    rt_lower = (room_type or "").lower()
    inferred_adults = 4 if ("family" in rt_lower or "suite" in rt_lower) else (2 if ("double" in rt_lower or "twin" in rt_lower or "deluxe" in rt_lower) else 1)
    if max_adults < inferred_adults:
        max_adults = inferred_adults
        try:
            frappe.db.set_value("Hotel Room Type", room_type, {
                "max_adults": max_adults,
                "max_occupancy": max(max_adults + 2, cint(rt.max_occupancy or 0))
            })
        except Exception:
            pass

    # If requested adults matches standard occupancy for this room category, auto-upgrade
    if adults > max_adults and adults <= inferred_adults:
        max_adults = inferred_adults
        try:
            frappe.db.set_value("Hotel Room Type", room_type, "max_adults", max_adults)
        except Exception:
            pass

    if max_adults and adults > max_adults:
        frappe.throw(_("{0} allows at most {1} adults.").format(room_type, max_adults))
    if cint(rt.max_children) and children > cint(rt.max_children):
        frappe.throw(_("{0} allows at most {1} children.").format(room_type, rt.max_children))
    if cint(rt.max_occupancy) and adults + children > max(cint(rt.max_occupancy), max_adults + 2):
        frappe.throw(_("{0} allows at most {1} guests.").format(room_type, max(cint(rt.max_occupancy), max_adults + 2)))


def validate_reservation_dates(check_in_date, check_out_date):
    try:
        ci, co = getdate(check_in_date), getdate(check_out_date)
    except Exception:
        ci = co = None
    if not ci or not co:
        frappe.throw(_("Please enter valid check-in and check-out dates."))
    if co <= ci:
        frappe.throw(_("Check-out date must be after check-in date."))
    return ci, co


def get_room_type_availability(room_type, check_in_date, check_out_date, exclude_reservation=None, for_update=False):
    """Inventory for [check_in, check_out): eligible rooms minus the peak number of active bookings
    of this room type on any night. Bookings count once whether or not a physical room is assigned."""
    ci, co = validate_reservation_dates(check_in_date, check_out_date)
    lock = " FOR UPDATE" if for_update else ""
    rooms = frappe.db.sql(f"""
        SELECT name, status FROM `tabHotel Room`
        WHERE room_type = %s AND is_enabled = 1 ORDER BY name{lock}
    """, room_type, as_dict=True)
    # Out-of-order rooms are never sold.
    total = len([r for r in rooms if r.status != RoomStatus.OUT_OF_ORDER])

    segments = frappe.db.sql(f"""
        SELECT r.name,
               COALESCE(s.from_date, r.check_in_date) AS frm,
               COALESCE(s.to_date, r.check_out_date) AS `to`
        FROM `tabHotel Reservation` r
        LEFT JOIN `tabHotel Reservation Stay` s ON s.parent = r.name AND s.parenttype = 'Hotel Reservation'
        WHERE r.status IN ('Reserved', 'Checked In')
          AND r.name != %(exclude)s
          AND COALESCE(s.room_type, r.room_type) = %(rt)s
          AND COALESCE(s.from_date, r.check_in_date) < %(co)s
          AND COALESCE(s.to_date, r.check_out_date) > %(ci)s
        {"LOCK IN SHARE MODE" if for_update else ""}
    """, {"exclude": exclude_reservation or "", "rt": room_type, "ci": ci, "co": co}, as_dict=True)

    peak = 0
    for i in range(date_diff(co, ci)):
        night = add_days(ci, i)
        booked = {g.name for g in segments if getdate(g.frm) <= night < getdate(g.to)}
        peak = max(peak, len(booked))
    return {"room_type": room_type, "total": total, "booked": peak, "available": max(total - peak, 0)}


@frappe.whitelist()
def move_room(reservation_name, new_room, reason=None, keep_rate=0):
    frappe.db.get_value("Hotel Reservation", reservation_name, "status", for_update=True)
    frappe.db.get_value("Hotel Room", new_room, "status", for_update=True)
    res = frappe.get_doc("Hotel Reservation", reservation_name)
    if res.status != ReservationStatus.CHECKED_IN:
        frappe.throw(_("Only Checked In reservations can move rooms."))
    if new_room == res.room:
        frappe.throw(_("Guest is already in room {0}.").format(new_room))

    new_room_doc = frappe.get_doc("Hotel Room", new_room)
    if new_room_doc.status != RoomStatus.AVAILABLE:
        frappe.throw(_("New room {0} is not Available (current status: {1}).").format(new_room, new_room_doc.status))

    today = getdate()
    old_room = res.room

    last_stay = res.stays[-1] if res.stays else None
    if last_stay:
        last_stay.to_date = today
        last_stay.nights = max(date_diff(last_stay.to_date, last_stay.from_date), 0)

    if int(keep_rate) and last_stay:
        new_rate = last_stay.rate
    else:
        new_rate = get_room_rate(new_room_doc.room_type, today, res.customer)

    remaining_nights = max(date_diff(res.check_out_date, today), 1)
    res.append("stays", {
        "room": new_room,
        "room_type": new_room_doc.room_type,
        "from_date": today,
        "to_date": res.check_out_date,
        "rate": new_rate,
        "nights": remaining_nights,
        "move_reason": reason
    })

    res.room = new_room
    res.room_type = new_room_doc.room_type
    res.save()

    has_open_issue = frappe.db.exists("Issue", {
        "hotel_room": old_room,
        "status": ["in", ["Open", "Replied", "Hold"]]
    })
    old_room_status = RoomStatus.OUT_OF_ORDER if has_open_issue else RoomStatus.DIRTY
    set_room_status(old_room, old_room_status, reason=f"Guest moved to room {new_room}")
    set_room_status(new_room, RoomStatus.OCCUPIED, reason=f"Guest moved from room {old_room}", reservation=res.name)

    return {"status": "success", "new_room": new_room}


@frappe.whitelist()
def cancel_reservation(reservation_name):
    res = frappe.get_doc("Hotel Reservation", reservation_name)
    if res.status != ReservationStatus.RESERVED:
        frappe.throw(_("Only Reserved stays can be cancelled."))

    # Clean up any flagged room drafts if confirmed
    flagged_drafts = frappe.get_all(
        "Sales Invoice",
        filters={"hotel_reservation": res.name, "charge_to_room": 1, "docstatus": 0},
        pluck="name"
    )
    for dname in flagged_drafts:
        frappe.delete_doc("Sales Invoice", dname, ignore_permissions=True, force=True)

    res.status = ReservationStatus.CANCELLED
    res.save()

    advances = frappe.db.sql("""
        SELECT name, paid_amount FROM `tabPayment Entry`
        WHERE hotel_reservation = %s AND docstatus = 1
    """, res.name, as_dict=True)
    if advances:
        frappe.msgprint(_("Reservation cancelled. Note: advance payments exist ({0}). Please refund using standard Payment Entry if required.").format(
            ", ".join([a.name for a in advances])
        ))

    return {"status": res.status}


def build_sales_invoice(reservation_name, as_of=None):
    """
    Builds an unsaved Sales Invoice document for the reservation stay segments.
    """
    res = frappe.get_doc("Hotel Reservation", reservation_name)
    settings = get_settings()
    as_of = getdate(as_of) if as_of else getdate()

    inv = frappe.new_doc("Sales Invoice")
    inv.customer = res.customer
    inv.company = res.company or get_company()
    inv.hotel_reservation = res.name
    inv.posting_date = as_of
    inv.due_date = as_of

    if settings.sales_taxes_template:
        inv.taxes_and_charges = settings.sales_taxes_template
    if settings.cost_center:
        inv.cost_center = settings.cost_center

    # Advances are allocated explicitly in allocate_reservation_advances(): only Payment
    # Entries linked to THIS reservation may be consumed (never other stays' deposits).
    inv.allocate_advances_automatically = 0
    inv.hotel_order_type = "Stay Checkout"

    total_nights_stayed = 0
    lines_added = 0

    for i, row in enumerate(res.stays):
        # Calculate nights
        row_from = getdate(row.from_date)
        if row.to_date and i < len(res.stays) - 1:
            row_to = getdate(row.to_date)
        else:
            # Last open row bills up to as_of
            row_to = as_of

        nights = max(date_diff(row_to, row_from), 0)
        total_nights_stayed += nights

        if nights > 0:
            item_code = get_room_item(row.room_type)
            inv.append("items", {
                "item_code": item_code,
                "qty": nights,
                "rate": row.rate,
                "description": _("Room {0} ({1}) from {2} to {3}").format(
                    row.room, row.room_type, row_from, row_to
                )
            })
            lines_added += 1

    # Check minimum billable nights
    min_nights = int(settings.min_billable_nights or 1)
    if total_nights_stayed < min_nights and res.stays:
        first_row = res.stays[0]
        needed_nights = min_nights - total_nights_stayed
        if inv.items:
            inv.items[0].qty += needed_nights
        else:
            item_code = get_room_item(first_row.room_type)
            inv.append("items", {
                "item_code": item_code,
                "qty": needed_nights,
                "rate": first_row.rate,
                "description": _("Room {0} ({1}) [Minimum Stay]").format(first_row.room, first_row.room_type)
            })

    # Append lines from unpaid flagged Charge to Room POS drafts
    flagged_drafts = frappe.get_all(
        "Sales Invoice",
        filters={
            "hotel_reservation": res.name,
            "charge_to_room": 1,
            "docstatus": 0
        },
        fields=["name", "additional_discount_percentage", "discount_amount", "net_total", "grand_total"],
        order_by="creation asc"
    )

    update_stock = int(settings.update_stock_on_checkout or 0)
    inv.update_stock = update_stock

    for draft in flagged_drafts:
        draft_items = frappe.get_all(
            "Sales Invoice Item",
            filters={"parent": draft.name},
            fields=[
                "item_code", "item_name", "description", "qty", "uom",
                "rate", "discount_percentage", "discount_amount", "cost_center"
            ]
        )
        for item in draft_items:
            # If draft had document-level discount percentage, ensure it applies
            item_discount = flt(item.discount_percentage)
            if not item_discount and draft.additional_discount_percentage:
                item_discount = flt(draft.additional_discount_percentage)

            inv.append("items", {
                "item_code": item.item_code,
                "item_name": item.item_name,
                "description": item.description or item.item_name,
                "qty": item.qty,
                "uom": item.uom,
                "rate": item.rate,
                "discount_percentage": item_discount,
                "cost_center": item.cost_center or settings.cost_center,
                "hotel_source_invoice": draft.name
            })

    inv.set_missing_values()
    inv.calculate_taxes_and_totals()
    allocate_reservation_advances(inv, res.name)
    return inv


def allocate_reservation_advances(inv, reservation_name):
    """Fill inv.advances using ERPNext's own advance lookup, restricted to Payment Entries
    whose hotel_reservation is this reservation, allocated up to the invoice total."""
    own_pes = set(frappe.get_all(
        "Payment Entry",
        filters={"hotel_reservation": reservation_name, "docstatus": 1, "payment_type": "Receive"},
        pluck="name",
    ))
    inv.set("advances", [])
    if not own_pes:
        return
    entries = inv.get_advance_entries()
    remaining = flt(inv.rounded_total or inv.grand_total)
    for e in entries:
        if e.reference_type != "Payment Entry" or e.reference_name not in own_pes or remaining <= 0:
            continue
        allocated = min(flt(e.amount), remaining)
        row = {
            "doctype": inv.doctype + " Advance",
            "reference_type": e.reference_type,
            "reference_name": e.reference_name,
            "reference_row": e.reference_row,
            "remarks": e.remarks,
            "advance_amount": flt(e.amount),
            "allocated_amount": allocated,
            "ref_exchange_rate": flt(e.exchange_rate),
            "difference_posting_date": inv.posting_date,
        }
        if e.get("paid_from"):
            row["account"] = e.paid_from
        if e.get("paid_to"):
            row["account"] = e.paid_to
        inv.append("advances", row)
        remaining -= allocated
    inv.calculate_taxes_and_totals()


@frappe.whitelist()
def get_billing_summary(reservation_name):
    """
    Computes estimated_total, total_paid, balance, room_service_pending, and room_service_paid.
    """
    res = frappe.get_doc("Hotel Reservation", reservation_name)

    # 1. Estimated Total
    if res.sales_invoice and frappe.db.exists("Sales Invoice", res.sales_invoice):
        inv = frappe.get_doc("Sales Invoice", res.sales_invoice)
        estimated_total = flt(inv.grand_total)
    else:
        inv = build_sales_invoice(reservation_name)
        estimated_total = flt(inv.grand_total)

    # 2. Total Paid
    # A) Advance payment entries linked to reservation
    pe_total = frappe.db.sql("""
        SELECT SUM(paid_amount) FROM `tabPayment Entry`
        WHERE hotel_reservation = %s
        AND payment_type = 'Receive'
        AND docstatus = 1
    """, reservation_name)[0][0] or 0.0

    # B) If invoice submitted, any direct invoice payment
    inv_paid = 0.0
    if res.sales_invoice and frappe.db.exists("Sales Invoice", res.sales_invoice):
        inv_doc = frappe.get_doc("Sales Invoice", res.sales_invoice)
        inv_paid = flt(inv_doc.outstanding_amount)

    if res.sales_invoice:
        total_paid = flt(estimated_total - inv_paid)
    else:
        total_paid = flt(pe_total)

    balance = flt(estimated_total - total_paid, 2)

    # 3. Room Service Drafts and Paid metrics
    pending_room_orders = frappe.db.sql("""
        SELECT SUM(grand_total) FROM `tabSales Invoice`
        WHERE hotel_reservation = %s
        AND charge_to_room = 1
        AND docstatus = 0
    """, reservation_name)[0][0] or 0.0

    paid_room_orders = frappe.db.sql("""
        SELECT SUM(grand_total) FROM `tabSales Invoice`
        WHERE hotel_reservation = %s
        AND hotel_order_type = 'Room Service'
        AND docstatus = 1
        AND name != %s
    """, (reservation_name, res.sales_invoice or "None"))[0][0] or 0.0

    # Update on doc if changed
    if res.estimated_total != estimated_total or res.total_paid != total_paid or res.balance != balance:
        frappe.db.set_value("Hotel Reservation", res.name, {
            "estimated_total": estimated_total,
            "total_paid": total_paid,
            "balance": balance
        }, update_modified=False)

    return {
        "estimated_total": estimated_total,
        "total_paid": total_paid,
        "balance": balance,
        "sales_invoice": res.sales_invoice,
        "room_service_pending": flt(pending_room_orders, 2),
        "room_service_paid": flt(paid_room_orders, 2)
    }


@frappe.whitelist()
def check_out(reservation_name):
    # Lock reservation row during checkout
    res_status = frappe.db.get_value("Hotel Reservation", reservation_name, "status", for_update=True)
    if res_status != ReservationStatus.CHECKED_IN:
        frappe.throw(_("Only Checked In reservations can be checked out."))

    res = frappe.get_doc("Hotel Reservation", reservation_name)
    if res.sales_invoice and frappe.db.get_value("Sales Invoice", res.sales_invoice, "docstatus") == 1:
        frappe.throw(_("Reservation {0} is already invoiced ({1}).").format(res.name, res.sales_invoice))

    today = getdate()
    settings = get_settings()

    # Close last stay segment
    if res.stays:
        last_stay = res.stays[-1]
        last_stay.to_date = today
        last_stay.nights = max(date_diff(today, getdate(last_stay.from_date)), 0)

    # Check balance tolerance
    billing = get_billing_summary(reservation_name)
    tolerance = flt(settings.balance_tolerance or 0.0)
    if settings.block_checkout_if_balance and billing["balance"] > tolerance:
        frappe.throw(_("Cannot check out. Outstanding balance is {0}. Please receive payment first.").format(
            billing["balance"]
        ))

    # Fetch flagged drafts before building invoice
    flagged_draft_names = frappe.get_all(
        "Sales Invoice",
        filters={
            "hotel_reservation": res.name,
            "charge_to_room": 1,
            "docstatus": 0
        },
        pluck="name"
    )

    # Build and submit Sales Invoice
    inv = build_sales_invoice(reservation_name, as_of=today)
    inv.insert(ignore_permissions=True)
    inv.submit()

    # Delete merged drafts and add audit comment
    if flagged_draft_names:
        for dname in flagged_draft_names:
            frappe.delete_doc("Sales Invoice", dname, ignore_permissions=True, force=True)
        inv.add_comment("Comment", _("Merged room orders: {0}").format(", ".join(flagged_draft_names)))

    res.sales_invoice = inv.name
    res.status = ReservationStatus.CHECKED_OUT
    res.checked_out_on = now_datetime()
    res.save()

    # Update room status: Out of Order if open issue, else Dirty
    has_open_issue = frappe.db.exists("Issue", {
        "hotel_room": res.room,
        "status": ["in", ["Open", "Replied", "Hold"]]
    })
    room_status = RoomStatus.OUT_OF_ORDER if has_open_issue else RoomStatus.DIRTY
    set_room_status(res.room, room_status, reason=f"Check-out {res.name}")

    return {
        "status": res.status,
        "sales_invoice": inv.name
    }


def get_conflicting_reservation(room, from_date, to_date, exclude=None):
    """Return the name of another active reservation occupying `room` in [from_date, to_date)."""
    rows = frappe.db.sql("""
        SELECT DISTINCT r.name
        FROM `tabHotel Reservation` r
        LEFT JOIN `tabHotel Reservation Stay` s ON s.parent = r.name
        WHERE COALESCE(s.room, r.room) = %(room)s
          AND r.name != %(exclude)s
          AND r.status IN ('Reserved', 'Checked In')
          AND COALESCE(s.from_date, r.check_in_date) < %(to)s
          AND COALESCE(s.to_date, r.check_out_date) > %(frm)s
        LIMIT 1
    """, {"room": room, "exclude": exclude or "", "frm": from_date, "to": to_date})
    return rows[0][0] if rows else None


def mark_todays_arrivals():
    """Daily: flag rooms of today's arrivals as Reserved (only if currently Available)."""
    today = getdate()
    for r in frappe.get_all("Hotel Reservation",
                            filters={"status": ReservationStatus.RESERVED, "check_in_date": ["<=", today], "room": ["is", "set"]},
                            fields=["name", "room"]):
        if frappe.db.get_value("Hotel Room", r.room, "status") == RoomStatus.AVAILABLE:
            set_room_status(r.room, RoomStatus.RESERVED, reason=f"Arrival due: {r.name}", reservation=r.name)
