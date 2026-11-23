/**
 * Shared check-in dialog: guest summary, identity verification and physical room allocation.
 * Used by the Front Desk Console and the Hotel Reservation form. All checks are repeated on the server.
 * Identity values live only in this dialog's memory: nothing is written to browser storage.
 */
function hospitality_core_checkin_dialog(reservation_name, on_done) {
    const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
    frappe.call({
        method: "hospitality_core.api.console.get_checkin_details",
        args: { reservation_name },
        freeze: true,
    }).then(({ message: data }) => {
        if (!data) return;
        const r = data.reservation;
        const rooms = data.rooms || [];
        const guests = `${r.adults || 0} ${__("adults")}${r.children ? `, ${r.children} ${__("children")}` : ""}`;
        const summary = `
            <table class="table table-sm table-borderless mb-2"><tbody>
                <tr><td class="text-muted">${__("Guest")}</td><td><b>${esc(r.guest_name)}</b></td>
                    <td class="text-muted">${__("Mobile")}</td><td>${esc(r.mobile_no || "—")}</td></tr>
                <tr><td class="text-muted">${__("Reservation")}</td><td>${esc(r.name)}</td>
                    <td class="text-muted">${__("Room Type")}</td><td>${esc(r.room_type)}</td></tr>
                <tr><td class="text-muted">${__("Stay")}</td><td>${frappe.datetime.str_to_user(r.check_in_date)} → ${frappe.datetime.str_to_user(r.check_out_date)}</td>
                    <td class="text-muted">${__("Guests")}</td><td>${esc(guests)}</td></tr>
            </tbody></table>`;
        const options = [""].concat(rooms.map((x) => ({
            value: x.name,
            label: `${x.room_number || x.name}${x.floor ? " · " + __("Floor") + " " + x.floor : ""}`,
        })));
        const d = new frappe.ui.Dialog({
            title: __("Check In · {0}", [r.name]),
            size: "large",
            fields: [
                { fieldtype: "HTML", fieldname: "summary", options: summary },
                { fieldtype: "Section Break", label: __("Identity Verification") },
                { fieldtype: "Select", fieldname: "guest_id_type", label: __("ID Type"), reqd: data.require_id ? 1 : 0,
                  options: ["", "Aadhaar", "PAN", "Driving Licence", "Passport", "Voter ID", "Other"] },
                { fieldtype: "Data", fieldname: "guest_id_number", label: __("ID Number"), reqd: data.require_id ? 1 : 0,
                  description: __("Stored for authorised staff only; shown masked elsewhere.") },
                { fieldtype: "Column Break" },
                { fieldtype: "Attach", fieldname: "guest_id_document", label: __("ID Document (optional)"),
                  options: { make_attachments_public: false, allow_web_link: false, allow_take_photo: true,
                             restrictions: { allowed_file_types: [".jpg", ".jpeg", ".png", ".webp", ".pdf"], max_file_size: 5 * 1024 * 1024 } } },
                { fieldtype: "Section Break", label: __("Room Allocation") },
                { fieldtype: "Select", fieldname: "room", label: __("Room"), reqd: 1, options,
                  default: r.room && rooms.some((x) => x.name === r.room) ? r.room : "",
                  description: rooms.length
                    ? __("{0} {1} room(s) free for this stay", [rooms.length, esc(r.room_type)])
                    : __("No {0} room is ready for check-in. Clean or release a room first.", [esc(r.room_type)]) },
            ],
            primary_action_label: __("Confirm Check-in"),
            primary_action(v) {
                return frappe.call({
                    method: "hospitality_core.api.console.check_in",
                    args: { reservation_name, room: v.room, guest_id_type: v.guest_id_type,
                            guest_id_number: v.guest_id_number, guest_id_document: v.guest_id_document },
                    freeze: true,
                    freeze_message: __("Checking in…"),
                }).then((res) => {
                    if (!res || res.exc) return;
                    d.hide();
                    frappe.show_alert({ message: __("{0} checked in to room {1}", [esc(r.guest_name), esc(res.message.reservation.room)]), indicator: "green" });
                    if (on_done) on_done(res.message);
                });
            },
        });
        d.onhide = () => d.$wrapper.remove();  // drop the typed ID from the DOM
        d.show();
    });
}
