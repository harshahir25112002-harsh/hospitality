/**
 * Front Desk Console - operation dialogs. Mixed into FrontDeskConsole.prototype.
 * Every operation stays inside a popup; server methods enforce all validation.
 */
Object.assign(FrontDeskConsole.prototype, {

    // ---------------- ROOM ----------------
    show_room_dialog(room) {
        if (room.reservation) return this.dialog_reservation(room.reservation, room);
        const me = this;
        const d = FD.dialog({
            title: __("Room {0}", [room.room_number || room.name]),
            fields: [{ fieldtype: "HTML", fieldname: "body" }],
        });
        d.fields_dict.body.$wrapper.html(`
            <div class="fd-modal-head">${FD.room_pill(room.status)}<span class="text-muted">${FD.esc(room.room_type)}${room.floor ? ` · ${__("Floor")} ${FD.esc(room.floor)}` : ""}</span></div>
            ${room.notes ? `<div class="fd-note">${FD.esc(room.notes)}</div>` : ""}
            <div class="fd-modal-actions"></div>`);
        const $a = d.fields_dict.body.$wrapper.find(".fd-modal-actions");
        const add = (label, cls, fn) => $(`<button class="btn btn-sm ${cls}">${label}</button>`).appendTo($a).on("click", () => { d.hide(); fn(); });
        if (room.status === "Available") {
            add(__("Walk-in"), "btn-success", () => me.dialog_walkin(room.name, room.room_type));
            add(__("New Reservation"), "btn-primary", () => me.dialog_new_reservation(null, room.room_type));
            add(__("Mark Dirty"), "btn-default", () => me.set_room_housekeeping(room.name, "Dirty"));
            add(__("Report Issue"), "btn-danger-light", () => me.dialog_report_issue(room.name));
        } else if (room.status === "Dirty") {
            add(__("Mark Clean"), "btn-success", () => me.set_room_housekeeping(room.name, "Clean"));
            add(__("Report Issue"), "btn-danger-light", () => me.dialog_report_issue(room.name));
        } else if (room.status === "Out of Order") {
            add(__("View Maintenance"), "btn-default", () => me.switch_tab("maintenance"));
        } else {
            add(__("Report Issue"), "btn-danger-light", () => me.dialog_report_issue(room.name));
        }
        d.show();
    },

    set_room_housekeeping(room, action) {
        return FD.call("hospitality_core.api.console.set_housekeeping", { room_number: room, action })
            .then((r) => this.done(null, __("Room {0} is now {1}", [room, __(r.status)])));
    },

    // ---------------- RESERVATION / GUEST DETAIL ----------------
    dialog_reservation(name) {
        const me = this;
        FD.call("hospitality_core.api.console.get_reservation_details", { reservation_name: name }, { freeze: true }).then((data) => {
            const r = data.reservation, g = data.guest || {}, b = data.billing || {};
            const d = FD.dialog({
                title: `${g.customer_name || r.customer} · ${r.name}`,
                size: "large",
                fields: [{ fieldtype: "HTML", fieldname: "body" }],
            });
            const pay_rows = (data.payments || []).map((p) => `<tr>
                <td>${FD.date(p.posting_date)}</td><td>${fd_doc_link("Payment Entry", p.name)}</td>
                <td>${FD.esc(p.mode_of_payment)}</td><td>${FD.esc(p.reference_no || "")}</td><td class="text-right">${FD.money(p.paid_amount)}</td></tr>`).join("");
            const order_rows = (data.room_orders || []).map((o) => `<tr>
                <td>${FD.date(o.posting_date)}</td><td>${fd_doc_link("Sales Invoice", o.name)}</td>
                <td>${o.charge_to_room ? `<span class="indicator-pill orange">${__("Charged to room")}</span>` : `<span class="indicator-pill green">${__("Paid")}</span>`}</td>
                <td class="text-right">${FD.money(o.grand_total)}</td></tr>`).join("");
            const stays = data.stays.length > 1 ? `<div class="fd-sec-title">${__("Room History")}</div>
                <table class="table table-sm fd-mini"><tbody>${data.stays.map((s) => `<tr><td>${FD.esc(s.room)}</td><td>${FD.esc(s.room_type)}</td>
                <td>${FD.date(s.from_date)} → ${FD.date(s.to_date)}</td><td class="text-right">${FD.money(s.rate)}</td></tr>`).join("")}</tbody></table>` : "";
            d.fields_dict.body.$wrapper.html(`
                <div class="fd-modal-head">${FD.pill(r.status)}<span class="text-muted">${__("Room")} <b>${FD.esc(r.room || __("Not Assigned"))}</b> · ${FD.esc(r.room_type)}</span></div>
                <div class="fd-detail-grid">
                    <div class="fd-card-sm">
                        <div class="fd-sec-title">${__("Guest")}</div>
                        ${FD.kv([[__("Name"), g.customer_name || r.customer], [__("Mobile"), g.mobile_no], [__("Email"), g.email_id],
                            [__("ID"), g.guest_id_number ? `${g.guest_id_type || ""} ${g.guest_id_number}${g.id_document_attached ? " · " + __("document on file") : ""}` : ""], [__("Guests"), `${r.adults || 0} ${__("adults")}${r.children ? `, ${r.children} ${__("children")}` : ""}`]])}
                    </div>
                    <div class="fd-card-sm">
                        <div class="fd-sec-title">${__("Stay")}</div>
                        ${FD.kv([[__("Check-in"), FD.date(r.check_in_date)], [__("Check-out"), FD.date(r.check_out_date)], [__("Nights"), r.nights],
                            [__("Room Rate"), FD.money(r.rate)], [__("Invoice"), r.sales_invoice ? fd_doc_link("Sales Invoice", r.sales_invoice) : "", true]])}
                    </div>
                </div>
                ${b && b.estimated_total !== undefined ? `
                <div class="fd-money-row">
                    <div><span>${__("Total Stay")}</span><b>${FD.money(b.estimated_total)}</b></div>
                    <div><span>${__("Paid")}</span><b class="text-success">${FD.money(b.total_paid)}</b></div>
                    <div><span>${__("Room Service Pending")}</span><b class="text-warning">${FD.money(b.room_service_pending)}</b></div>
                    <div class="fd-money-due"><span>${__("Outstanding")}</span><b class="${b.balance > 0 ? "text-danger" : "text-success"}">${FD.money(b.balance)}</b></div>
                </div>` : ""}
                ${stays}
                <div class="fd-sec-title">${__("Payments")}</div>
                ${pay_rows ? `<table class="table table-sm fd-mini"><tbody>${pay_rows}</tbody></table>` : `<div class="text-muted small mb-3">${__("No payments yet.")}</div>`}
                <div class="fd-online-payments"></div>
                ${order_rows ? `<div class="fd-sec-title">${__("Room Service Orders")}</div><table class="table table-sm fd-mini"><tbody>${order_rows}</tbody></table>` : ""}
                <div class="fd-modal-actions"></div>`);
            me.render_online_payments(d.fields_dict.body.$wrapper.find(".fd-online-payments"), r.name);

            const $a = d.fields_dict.body.$wrapper.find(".fd-modal-actions");
            const add = (label, cls, fn) => $(`<button class="btn btn-sm ${cls}">${label}</button>`).appendTo($a).on("click", () => { d.hide(); fn(); });
            if (r.status === "Reserved") {
                add(__("Check In"), "btn-primary", () => me.dialog_checkin(r.name));
                add(__("Receive Advance"), "btn-default", () => me.dialog_receive_payment(r.name));
                add(__("Change Dates"), "btn-default", () => me.dialog_extend_stay(r.name));
                add(__("Cancel Reservation"), "btn-danger-light", () => me.dialog_cancel(r.name));
            } else if (r.status === "Checked In") {
                add(__("Receive Payment"), "btn-primary", () => me.dialog_receive_payment(r.name, b.balance));
                add(__("Room Service"), "btn-default", () => me.open_room_service_for(r.name, r.customer));
                add(__("Move Room"), "btn-default", () => me.dialog_move_room(r.name));
                add(__("Extend Stay"), "btn-default", () => me.dialog_extend_stay(r.name));
                add(__("View Bill"), "btn-default", () => me.dialog_bill_preview(r.name));
                if (r.room) add(__("Report Issue"), "btn-default", () => me.dialog_report_issue(r.room));
                add(__("Check Out"), "btn-dark", () => me.dialog_checkout(r.name));
            } else if (r.sales_invoice) {
                add(__("Print Invoice"), "btn-primary", () => fd_open_print_popup("Sales Invoice", r.sales_invoice));
                me.rzp_config().then((c) => {
                    if (!c.invoice) return;
                    frappe.db.get_value("Sales Invoice", r.sales_invoice, ["outstanding_amount", "docstatus"]).then((x) => {
                        const inv = x.message || {};
                        if (inv.docstatus === 1 && inv.outstanding_amount > 0) {
                            add(__("Collect Invoice Online ({0})", [FD.money(inv.outstanding_amount)]), "btn-default",
                                () => me.start_online_payment({ sales_invoice: r.sales_invoice }, inv.outstanding_amount, g.customer_name));
                        }
                    });
                });
            }
            d.show();
        });
    },

    dialog_guest(customer) {
        const me = this;
        Promise.all([
            frappe.db.get_value("Customer", customer, ["customer_name", "mobile_no", "email_id"]),
            FD.call("hospitality_core.api.console.get_reservations", { text: customer, limit: 20 }),
        ]).then(([c, rows]) => {
            const g = c.message || {};
            const d = FD.dialog({ title: g.customer_name || customer, fields: [{ fieldtype: "HTML", fieldname: "body" }] });
            d.fields_dict.body.$wrapper.html(`
                ${FD.kv([[__("Mobile"), g.mobile_no], [__("Email"), g.email_id]])}
                <div class="fd-sec-title">${__("Reservations")}</div>
                ${(rows || []).length ? `<table class="table table-sm fd-mini"><tbody>${rows.map((r) => `<tr class="fd-click" data-res="${FD.esc(r.name)}">
                    <td>${FD.esc(r.name)}</td><td>${FD.esc(r.room || __("Not Assigned"))}</td><td>${FD.date(r.check_in_date)} → ${FD.date(r.check_out_date)}</td><td>${FD.pill(r.status)}</td></tr>`).join("")}</tbody></table>`
                    : `<div class="text-muted small">${__("No reservations.")}</div>`}`);
            d.fields_dict.body.$wrapper.on("click", "[data-res]", function () { d.hide(); me.dialog_reservation($(this).data("res")); });
            d.set_primary_action(__("New Reservation"), () => { d.hide(); me.dialog_new_reservation(null, null, null, null, customer); });
            d.show();
        });
    },

    // ---------------- NEW RESERVATION / WALK-IN ----------------
    guest_fields(walkin) {
        return [
            { fieldtype: "HTML", fieldname: "guest_hint", options: `<div class="fd-sec-title">${__("Guest")}</div>` },
            { fieldtype: "Link", fieldname: "customer", label: __("Existing Guest"), options: "Customer",
              description: __("Search an existing guest, or fill the new guest fields below") },
            { fieldtype: "Data", fieldname: "guest_name", label: __("New Guest Name"), depends_on: "eval:!doc.customer" },
            { fieldtype: "Column Break" },
            { fieldtype: "Data", fieldname: "mobile_no", label: __("Mobile"), options: "Phone", depends_on: "eval:!doc.customer" },
            // Identity is verified only at check-in (walk-in = immediate check-in), never at booking.
            ...(walkin ? [
                { fieldtype: "Section Break", label: __("Identity Verification") },
                { fieldtype: "Select", fieldname: "guest_id_type", label: __("ID Type"), options: ["", "Aadhaar", "PAN", "Driving Licence", "Passport", "Voter ID", "Other"] },
                { fieldtype: "Column Break" },
                { fieldtype: "Data", fieldname: "guest_id_number", label: __("ID Number") },
            ] : []),
        ];
    },

    stay_fields(pre_room, pre_type, from, to, walkin) {
        const me = this;
        const today = frappe.datetime.get_today();
        return [
            { fieldtype: "Section Break", label: __("Stay") },
            { fieldtype: "Link", fieldname: "room_type", label: __("Room Type"), options: "Hotel Room Type", reqd: 1, default: pre_type,
              onchange: () => me._refresh_room_options() },
            { fieldtype: "Date", fieldname: "check_in_date", label: __("Check-in"), reqd: !walkin, read_only: walkin ? 1 : 0,
              default: walkin ? today : (from || me.current_date), onchange: () => me._refresh_room_options() },
            { fieldtype: "Date", fieldname: "check_out_date", label: __("Check-out"), reqd: 1,
              default: to || frappe.datetime.add_days(walkin ? today : (from || me.current_date), 1), onchange: () => me._refresh_room_options() },
            { fieldtype: "Column Break" },
            ...(walkin ? [{ fieldtype: "Select", fieldname: "room", label: __("Room"), reqd: 1, options: pre_room ? [pre_room] : [], default: pre_room,
              description: __("Only rooms free for the selected dates are listed") }] : []),
            { fieldtype: "Int", fieldname: "adults", label: __("Adults"), default: 1 },
            { fieldtype: "Int", fieldname: "children", label: __("Children"), default: 0 },
            { fieldtype: "HTML", fieldname: "rate_info" },
            { fieldtype: "Section Break", label: __("Advance Payment (optional)"), collapsible: 1 },
            { fieldtype: "Currency", fieldname: "advance_amount", label: __("Amount") },
            { fieldtype: "Column Break" },
            { fieldtype: "Link", fieldname: "advance_mode", label: __("Mode of Payment"), options: "Mode of Payment", default: me.state.settings.default_advance_mode },
            { fieldtype: "Data", fieldname: "advance_reference", label: __("Reference No") },
            { fieldtype: "Section Break" },
            { fieldtype: "Small Text", fieldname: "remarks", label: __("Remarks") },
        ];
    },

    _refresh_room_options() {
        const d = this._res_dialog;
        if (!d) return;
        const v = d.get_values(true);
        const field = d.fields_dict.room;
        if (!v.room_type || !v.check_in_date || !v.check_out_date || v.check_out_date <= v.check_in_date) {
            d.fields_dict.rate_info.$wrapper.html("");
            return;
        }
        if (!d.__walkin) {
            // Bookings hold room-type inventory; the physical room is allocated at check-in.
            return FD.call("hospitality_core.api.console.get_room_type_availability", {
                room_type: v.room_type, check_in_date: v.check_in_date, check_out_date: v.check_out_date,
            }).then((a) => {
                d.fields_dict.rate_info.$wrapper.html(a.available > 0
                    ? `<div class="fd-rate-box">${__("{0} of {1} rooms available", [a.available, a.total])} · ${FD.money(a.rate)} × ${a.nights} ${__("nights")} = <b>${FD.money(a.rate * a.nights)}</b></div>`
                    : `<div class="fd-rate-box fd-rate-none">${__("No {0} rooms available for these dates", [FD.esc(v.room_type)])}</div>`);
            }).catch(() => {});
        }
        FD.call("hospitality_core.api.console.get_available_rooms", {
            room_type: v.room_type, check_in_date: v.check_in_date, check_out_date: v.check_out_date,
        }).then((rooms) => {
            rooms = rooms || [];
            const keep = v.room && rooms.some((r) => r.name === v.room) ? v.room : (d.__pre_room && rooms.some((r) => r.name === d.__pre_room) ? d.__pre_room : "");
            field.df.options = [""].concat(rooms.map((r) => ({ value: r.name, label: `${r.room_number || r.name}${r.floor ? " · " + __("Floor") + " " + r.floor : ""}` })));
            field.refresh();
            field.set_value(keep || (d.__walkin && rooms[0] ? rooms[0].name : ""));
            const nights = frappe.datetime.get_diff(v.check_out_date, v.check_in_date);
            const rate = rooms[0] ? rooms[0].rate : 0;
            d.fields_dict.rate_info.$wrapper.html(rooms.length
                ? `<div class="fd-rate-box">${__("{0} rooms free", [rooms.length])} · ${FD.money(rate)} × ${nights} ${__("nights")} = <b>${FD.money(rate * nights)}</b></div>`
                : `<div class="fd-rate-box fd-rate-none">${__("No {0} rooms free for these dates", [FD.esc(v.room_type)])}</div>`);
        }).catch(() => {});
    },

    _reservation_dialog(walkin, pre_room, pre_type, from, to, customer) {
        const me = this;
        const d = FD.dialog({
            title: walkin ? __("Walk-in Check-in") : __("New Reservation"),
            size: "large",
            fields: [...this.guest_fields(walkin), ...this.stay_fields(pre_room, pre_type, from, to, walkin)],
            primary_action_label: walkin ? __("Check In Now") : __("Create Reservation"),
            primary_action(values) {
                if (!values.customer && !values.guest_name) {
                    frappe.msgprint(__("Select an existing guest or enter the new guest's name."));
                    return;
                }
                const data = {
                    customer: values.customer, guest_name: values.guest_name, mobile_no: values.mobile_no,
                    room_type: values.room_type, check_in_date: values.check_in_date,
                    check_out_date: values.check_out_date, adults: values.adults, children: values.children, remarks: values.remarks,
                };
                if (walkin) Object.assign(data, { room: values.room, guest_id_type: values.guest_id_type, guest_id_number: values.guest_id_number });
                const advance = values.advance_amount > 0 ? { amount: values.advance_amount, mode: values.advance_mode, reference_no: values.advance_reference } : null;
                return FD.call(`hospitality_core.api.console.${walkin ? "walk_in" : "create_reservation"}`, { data, advance }, { freeze: true })
                    .then((r) => {
                        me.done(d, walkin ? __("Guest checked in to room {0}", [r.reservation.room]) : __("Reservation {0} created", [r.reservation.name]));
                    });
            },
        });
        d.__pre_room = pre_room;
        d.__walkin = walkin;
        this._res_dialog = d;
        d.onhide = () => { if (me._res_dialog === d) me._res_dialog = null; };
        if (customer) d.set_value("customer", customer);
        d.show();
        this._refresh_room_options();
    },

    dialog_new_reservation(pre_room = null, pre_type = null, from = null, to = null, customer = null) {
        this._reservation_dialog(false, pre_room, pre_type, from, to, customer);
    },

    dialog_walkin(pre_room = null, pre_type = null) {
        this._reservation_dialog(true, pre_room, pre_type);
    },

    // ---------------- CHECK-IN ----------------
    dialog_checkin(res) {
        hospitality_core_checkin_dialog(res, (r) => this.done(null, __("Checked in to room {0}", [r.reservation.room])));
    },

    // ---------------- PAYMENT ----------------
    dialog_receive_payment(res, amount = null, after = null) {
        const me = this;
        const RECORD = __("Cash / Bank Transfer / Card (record payment)");
        const ONLINE = __("Razorpay Online Payment");
        const d = FD.dialog({
            title: __("Receive Payment · {0}", [res]),
            fields: [
                { fieldtype: "HTML", fieldname: "info" },
                { fieldtype: "Select", fieldname: "method", label: __("Payment Method"), options: [RECORD], default: RECORD, hidden: 1,
                  onchange() { d.get_primary_btn().text(d.get_value("method") === ONLINE ? __("Create Payment Request") : __("Receive")); } },
                { fieldtype: "Currency", fieldname: "amount", label: __("Amount"), reqd: 1, default: amount > 0 ? amount : null },
                { fieldtype: "Link", fieldname: "mode", label: __("Mode of Payment"), options: "Mode of Payment", default: me.state.settings.default_advance_mode,
                  depends_on: `eval:doc.method!=="${ONLINE}"`, mandatory_depends_on: `eval:doc.method!=="${ONLINE}"` },
                { fieldtype: "Data", fieldname: "reference", label: __("Reference No"), description: __("Card / UPI / cheque reference"), depends_on: `eval:doc.method!=="${ONLINE}"` },
                { fieldtype: "HTML", fieldname: "online_note", depends_on: `eval:doc.method==="${ONLINE}"`,
                  options: `<div class="fd-note">${__("A secure Razorpay checkout is created for this amount. The guest pays by QR code, link or on this screen; the payment is recorded automatically once Razorpay confirms it.")}</div>` },
            ],
            primary_action_label: __("Receive"),
            primary_action(v) {
                if (!(v.amount > 0)) { frappe.msgprint(__("Enter an amount greater than zero.")); return; }
                if (v.method === ONLINE) {
                    d.hide();
                    return me.start_online_payment({ reservation: res }, v.amount);
                }
                if (!v.mode) { frappe.msgprint(__("Select the Mode of Payment.")); return; }
                return FD.call("hospitality_core.api.console.receive_payment",
                    { reservation_name: res, mode: v.mode, amount: v.amount, reference: v.reference }, { freeze: true })
                    .then((r) => {
                        me.done(d, __("Payment {0} recorded. Balance {1}", [r.payment_entry, FD.money(r.billing.balance)]));
                        if (after) after(r);
                    });
            },
        });
        d.show();
        me.rzp_config().then((c) => {
            if (!c.front_desk) return;
            const f = d.fields_dict.method;
            f.df.options = [RECORD, ONLINE].join("\n");
            f.df.hidden = 0;
            f.refresh();
            d.fields_dict.mode.get_query = () => ({ filters: { enabled: 1, name: ["!=", c.mode_of_payment || ""] } });
        });
        FD.call("hospitality_core.api.console.get_bill_preview", { reservation_name: res }).then((b) => {
            d.fields_dict.info.$wrapper.html(`<div class="fd-money-row">
                <div><span>${__("Bill Total")}</span><b>${FD.money(b.grand_total)}</b></div>
                <div><span>${__("Paid")}</span><b class="text-success">${FD.money(b.total_paid)}</b></div>
                <div class="fd-money-due"><span>${__("Outstanding")}</span><b class="${b.balance > 0 ? "text-danger" : "text-success"}">${FD.money(b.balance)}</b></div></div>`);
            if (!d.get_value("amount") && b.balance > 0) d.set_value("amount", b.balance);
        }).catch(() => {});
    },

    // ---------------- BILL / CHECK-OUT ----------------
    bill_html(b) {
        return `
            <div class="fd-table-wrap"><table class="fd-table fd-bill">
                <thead><tr><th>${__("Description")}</th><th class="text-right">${__("Qty")}</th><th class="text-right">${__("Rate")}</th><th class="text-right">${__("Amount")}</th></tr></thead>
                <tbody>${(b.items || []).map((i) => `<tr>
                    <td>${FD.esc(i.description ? $("<div>").html(i.description).text() : i.item_name)}
                        ${i.source && i.source !== "Room Night" ? `<div class="small text-muted">${__("Room service")} · ${FD.esc(i.source)}</div>` : ""}</td>
                    <td class="text-right">${i.qty}</td><td class="text-right">${FD.money(i.rate)}</td><td class="text-right">${FD.money(i.amount)}</td></tr>`).join("")}
                    ${(b.taxes || []).map((t) => `<tr class="fd-bill-tax"><td colspan="3">${FD.esc(t.description)}</td><td class="text-right">${FD.money(t.tax_amount)}</td></tr>`).join("")}
                </tbody>
            </table></div>
            <div class="fd-money-row">
                <div><span>${__("Grand Total")}</span><b>${FD.money(b.grand_total)}</b></div>
                <div><span>${__("Paid / Advances")}</span><b class="text-success">${FD.money(b.total_paid)}</b></div>
                <div><span>${__("Room Service Paid at POS")}</span><b>${FD.money(b.room_service_paid)}</b><small class="text-muted">${__("not re-billed")}</small></div>
                <div class="fd-money-due"><span>${__("Outstanding")}</span><b class="${b.balance > 0 ? "text-danger" : "text-success"}">${FD.money(b.balance)}</b></div>
            </div>`;
    },

    dialog_bill_preview(res) {
        const me = this;
        FD.call("hospitality_core.api.console.get_bill_preview", { reservation_name: res }, { freeze: true }).then((b) => {
            const d = FD.dialog({
                title: __("Bill Preview · {0}", [res]), size: "large",
                fields: [{ fieldtype: "HTML", fieldname: "body" }],
                primary_action_label: __("Check Out"),
                primary_action: () => { d.hide(); me.dialog_checkout(res); },
            });
            d.fields_dict.body.$wrapper.html(me.bill_html(b));
            d.set_secondary_action_label(__("Receive Payment"));
            d.set_secondary_action(() => { d.hide(); me.dialog_receive_payment(res, b.balance); });
            d.show();
        });
    },

    dialog_checkout(res) {
        const me = this;
        const RECORD = __("Cash / Card / Bank");
        const ONLINE = __("Razorpay Online Checkout");

        FD.call("hospitality_core.api.console.get_bill_preview", { reservation_name: res }, { freeze: true }).then((b) => {
            const due = Math.max(b.balance || 0, 0);
            const d = FD.dialog({
                title: __("Check Out · {0}", [res]), size: "large",
                fields: [
                    { fieldtype: "HTML", fieldname: "bill" },
                    { fieldtype: "Section Break", label: due > 0 ? __("Settle Outstanding Now") : "" , hidden: due > 0 ? 0 : 1 },
                    { fieldtype: "Select", fieldname: "pay_method", label: __("Settlement Method"), options: [RECORD, ONLINE], default: RECORD,
                      onchange() {
                          const isOnline = d.get_value("pay_method") === ONLINE;
                          d.set_df_property("mode", "hidden", isOnline);
                          d.set_df_property("reference", "hidden", isOnline);
                          d.get_primary_btn().text(isOnline ? __("Initiate Razorpay & Check Out") : __("Confirm Check Out & Invoice"));
                      }
                    },
                    { fieldtype: "Currency", fieldname: "amount", label: __("Collect Amount"), default: due },
                    { fieldtype: "Column Break" },
                    { fieldtype: "Link", fieldname: "mode", label: __("Mode of Payment"), options: "Mode of Payment", default: me.state.settings.default_advance_mode },
                    { fieldtype: "Data", fieldname: "reference", label: __("Reference No") },
                ],
                primary_action_label: __("Confirm Check Out & Invoice"),
                primary_action(v) {
                    if (due > 0 && v.amount > 0 && v.pay_method === ONLINE) {
                        d.hide();
                        return me.start_online_payment({ reservation: res }, v.amount, b.customer_name).then(() => {
                            me.dialog_checkout(res);
                        });
                    }

                    const collect = due > 0 && v.amount > 0 ? { amount: v.amount, mode: v.mode, reference: v.reference } : null;
                    if (collect && !v.mode) { frappe.msgprint(__("Select the Mode of Payment.")); return; }
                    return FD.call("hospitality_core.api.console.check_out", { reservation_name: res, collect_payment: collect },
                        { freeze: true, freeze_message: __("Creating Sales Invoice…") })
                        .then((r) => {
                            me.done(d, __("Checked out. Invoice {0}", [r.sales_invoice]));
                            const s = FD.dialog({
                                title: __("Check-Out Completed"),
                                fields: [{ fieldtype: "HTML", fieldname: "b", options: `<div class="fd-success">${FD.icon("check", "lg")}
                                    <div>${__("Sales Invoice {0} submitted. The room is now marked Dirty for housekeeping.", [`<b>${FD.esc(r.sales_invoice)}</b>`])}</div></div>` }],
                                primary_action_label: __("Print Invoice"),
                                primary_action: () => fd_open_print_popup("Sales Invoice", r.sales_invoice),
                            });
                            s.show();
                        });
                },
            });
            d.fields_dict.bill.$wrapper.html(me.bill_html(b));
            d.show();
        });
    },

    // ---------------- ROOM CHANGES ----------------
    _room_select_dialog(title, res, method, note) {
        const me = this;
        FD.call("hospitality_core.api.console.get_reservation_details", { reservation_name: res }).then((data) => {
            const r = data.reservation;
            const from = r.status === "Checked In" ? frappe.datetime.get_today() : r.check_in_date;
            const d = FD.dialog({
                title, fields: [
                    { fieldtype: "HTML", fieldname: "info", options: `<div class="text-muted mb-2">${__("Current room")}: <b>${FD.esc(r.room || __("Not Assigned"))}</b> (${FD.esc(r.room_type)}) · ${FD.date(from)} → ${FD.date(r.check_out_date)}</div>` },
                    { fieldtype: "Link", fieldname: "room_type", label: __("Room Type"), options: "Hotel Room Type", reqd: 1, default: r.room_type, onchange: () => load() },
                    { fieldtype: "Select", fieldname: "room", label: __("New Room"), reqd: 1, options: [] },
                    ...(method === "move_room" ? [
                        { fieldtype: "Check", fieldname: "keep_rate", label: __("Keep current rate"), default: 1 },
                        { fieldtype: "Data", fieldname: "reason", label: __("Reason") },
                    ] : []),
                    ...(note ? [{ fieldtype: "HTML", fieldname: "note", options: `<div class="small text-muted">${note}</div>` }] : []),
                ],
                primary_action_label: __("Confirm"),
                primary_action(v) {
                    const args = method === "move_room"
                        ? { reservation_name: res, new_room: v.room, reason: v.reason, keep_rate: v.keep_rate }
                        : { reservation_name: res, new_room: v.room };
                    return FD.call(`hospitality_core.api.console.${method}`, args, { freeze: true })
                        .then(() => me.done(d, __("Room changed to {0}", [v.room])));
                },
            });
            const load = () => {
                const t = d.get_value("room_type");
                if (!t) return;
                FD.call("hospitality_core.api.console.get_available_rooms", {
                    room_type: t, check_in_date: from, check_out_date: r.check_out_date > from ? r.check_out_date : frappe.datetime.add_days(from, 1),
                    exclude_reservation: res,
                }).then((rooms) => {
                    const opts = (rooms || []).filter((x) => x.name !== r.room && (method !== "move_room" || x.status === "Available"));
                    d.fields_dict.room.df.options = [""].concat(opts.map((x) => ({ value: x.name, label: `${x.room_number || x.name} · ${FD.money(x.rate)}` })));
                    d.fields_dict.room.refresh();
                    if (!opts.length) d.fields_dict.room.set_description(__("No free rooms of this type for the remaining stay."));
                    else d.fields_dict.room.set_description("");
                });
            };
            d.show();
            load();
        });
    },

    dialog_move_room(res) {
        this._room_select_dialog(__("Move Room · {0}", [res]), res, "move_room",
            __("Nights so far stay billed on the old room; the old room goes to housekeeping (Dirty)."));
    },

    dialog_change_reserved_room(res) {
        this._room_select_dialog(__("Change Room · {0}", [res]), res, "change_reserved_room");
    },

    dialog_extend_stay(res) {
        const me = this;
        FD.call("hospitality_core.api.console.get_reservation_details", { reservation_name: res }).then((data) => {
            const r = data.reservation;
            const d = FD.dialog({
                title: r.status === "Checked In" ? __("Extend Stay · {0}", [res]) : __("Change Departure · {0}", [res]),
                fields: [
                    { fieldtype: "HTML", fieldname: "info", options: `<div class="text-muted mb-2">${__("Room")} <b>${FD.esc(r.room || __("Not Assigned"))}</b> · ${__("Current check-out")}: <b>${FD.date(r.check_out_date)}</b></div>` },
                    { fieldtype: "Date", fieldname: "new_date", label: __("New Check-out Date"), reqd: 1, default: frappe.datetime.add_days(r.check_out_date, 1) },
                ],
                primary_action_label: __("Update Stay"),
                primary_action(v) {
                    return FD.call("hospitality_core.api.console.extend_stay", { reservation_name: res, new_check_out_date: v.new_date }, { freeze: true })
                        .then((x) => me.done(d, __("Check-out moved to {0}. New total {1}", [FD.date(v.new_date), FD.money(x.billing.estimated_total)])));
                },
            });
            d.show();
        });
    },

    dialog_cancel(res) {
        const me = this;
        const d = FD.dialog({
            title: __("Cancel Reservation · {0}", [res]),
            fields: [
                { fieldtype: "HTML", fieldname: "w", options: `<div class="fd-note">${__("The room will be released. Any advance payment must be refunded with a standard Payment Entry (Pay).")}</div>` },
                { fieldtype: "Small Text", fieldname: "reason", label: __("Reason") },
            ],
            primary_action_label: __("Cancel Reservation"),
            primary_action(v) {
                return FD.call("hospitality_core.api.console.cancel_reservation", { reservation_name: res, reason: v.reason }, { freeze: true })
                    .then(() => me.done(d, __("Reservation {0} cancelled", [res]), "orange"));
            },
        });
        d.get_primary_btn().removeClass("btn-primary").addClass("btn-danger");
        d.show();
    },

    // ---------------- MAINTENANCE ----------------
    dialog_report_issue(pre_room = null) {
        const me = this;
        const d = FD.dialog({
            title: __("Report Maintenance Issue"),
            fields: [
                { fieldtype: "Link", fieldname: "room", label: __("Room"), options: "Hotel Room", reqd: 1, default: pre_room },
                { fieldtype: "Data", fieldname: "subject", label: __("Problem"), reqd: 1, placeholder: __("e.g. AC not cooling") },
                { fieldtype: "Select", fieldname: "priority", label: __("Priority"), options: "Low\nMedium\nHigh", default: "Medium" },
                { fieldtype: "Small Text", fieldname: "description", label: __("Details") },
            ],
            primary_action_label: __("Report"),
            primary_action(v) {
                return FD.call("hospitality_core.api.console.report_issue", v, { freeze: true })
                    .then((r) => me.done(d, __("Issue {0} reported", [r.issue]), "orange"));
            },
        });
        d.show();
    },

    dialog_resolve_issue(issue) {
        const me = this;
        const d = FD.dialog({
            title: __("Resolve Issue · {0}", [issue]),
            fields: [{ fieldtype: "Small Text", fieldname: "notes", label: __("Resolution Notes") }],
            primary_action_label: __("Mark Resolved"),
            primary_action(v) {
                return FD.call("hospitality_core.api.console.resolve_issue", { issue_name: issue, notes: v.notes }, { freeze: true })
                    .then((r) => me.done(d, __("Issue resolved. Room {0} released.", [r.room])));
            },
        });
        d.show();
    },

    // ---------------- SETTINGS ----------------
    dialog_hotel_settings() {
        const me = this;
        frappe.call({
            method: "frappe.client.get",
            args: { doctype: "Hotel Settings", name: "Hotel Settings" },
            callback: (r) => {
                const s = r.message || {};
                const d = FD.dialog({
                title: __("Hotel Settings"), size: "large",
                fields: [
                    { fieldtype: "Link", fieldname: "company", label: __("Company"), options: "Company", default: s.company },
                    { fieldtype: "Link", fieldname: "default_room_item", label: __("Default Room Item"), options: "Item", default: s.default_room_item },
                    { fieldtype: "Link", fieldname: "sales_taxes_template", label: __("Sales Taxes Template"), options: "Sales Taxes and Charges Template", default: s.sales_taxes_template },
                    { fieldtype: "Column Break" },
                    { fieldtype: "Link", fieldname: "restaurant_pos_profile", label: __("Restaurant POS Profile"), options: "POS Profile", default: s.restaurant_pos_profile },
                    { fieldtype: "Link", fieldname: "room_pos_profile", label: __("Room Service POS Profile"), options: "POS Profile", default: s.room_pos_profile },
                    { fieldtype: "Link", fieldname: "default_advance_mode", label: __("Default Mode of Payment"), options: "Mode of Payment", default: s.default_advance_mode },
                    { fieldtype: "Section Break" },
                    { fieldtype: "Check", fieldname: "allow_checkin_before_arrival", label: __("Allow check-in before arrival date"), default: s.allow_checkin_before_arrival },
                    { fieldtype: "Check", fieldname: "block_checkout_if_balance", label: __("Block check-out if balance due"), default: s.block_checkout_if_balance },
                    { fieldtype: "Column Break" },
                    { fieldtype: "Currency", fieldname: "balance_tolerance", label: __("Balance Tolerance"), default: s.balance_tolerance },
                    { fieldtype: "Int", fieldname: "min_billable_nights", label: __("Minimum Billable Nights"), default: s.min_billable_nights || 1 },
                ],
                primary_action_label: __("Save"),
                primary_action(v) {
                    return frappe.call({ method: "frappe.client.set_value", args: { doctype: "Hotel Settings", name: "Hotel Settings", fieldname: v } })
                        .then((r) => { if (!r.exc) me.done(d, __("Settings saved")); });
                },
            });
            d.show();
        });
    },

    // ---------------- WHATSAPP CONCIERGE & PRE-CHECK-IN ----------------
    dialog_whatsapp(resName, otaName) {
        const me = this;
        FD.call("hospitality_core.api.guest.get_whatsapp_links", {
            reservation_name: resName || null,
            ota_reservation_name: otaName || null
        }, { freeze: true, freeze_message: __("Preparing WhatsApp Concierge...") }).then((data) => {
            if (!data) return;

            const msgs = data.messages || {};
            let activeType = "welcome";

            const d = new frappe.ui.Dialog({
                title: __("WhatsApp Guest Concierge · {0}", [data.guest_name || __("Guest")]),
                size: "large",
                fields: [
                    {
                        fieldtype: "HTML",
                        fieldname: "wa_header",
                        options: `
                            <div style="background:#f0fdf4;border:1px solid #bbf7d0;padding:12px 16px;border-radius:10px;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between;">
                                <div>
                                    <div style="font-weight:700;color:#15803d;font-size:14px;">💬 WhatsApp Direct Guest Concierge</div>
                                    <div style="font-size:12px;color:#166534;">Guest Mobile: <b>${FD.esc(data.guest_phone || __("Not set"))}</b></div>
                                </div>
                                <a href="${FD.esc((data.precheckin_url && data.precheckin_url.indexOf('/api/method/') !== -1) ? data.precheckin_url.substring(data.precheckin_url.indexOf('/api/method/')) : (data.precheckin_url || '/api/method/hospitality_core.api.guest.portal?token=preview'))}" target="_blank" class="btn btn-default btn-xs" style="font-weight:600;">
                                    ${FD.icon("external-link")} <span>${__("Preview Web Portal")}</span>
                                </a>
                            </div>
                            <div class="fd-seg fd-wa-msg-type" style="margin-bottom:14px;">
                                <button type="button" class="fd-seg-btn active" data-type="welcome">⚡ ${__("1-Min Pre-Check-in Link")}</button>
                                <button type="button" class="fd-seg-btn" data-type="wifi">📶 ${__("WiFi & Digital Pass")}</button>
                                <button type="button" class="fd-seg-btn" data-type="bill">🧾 ${__("Folio & Checkout Bill")}</button>
                            </div>
                        `
                    },
                    {
                        fieldtype: "Small Text",
                        fieldname: "msg_content",
                        label: __("Message Text (Editable)"),
                        default: msgs.welcome ? msgs.welcome.text : ""
                    }
                ],
                primary_action_label: __("Open in WhatsApp 📱"),
                primary_action() {
                    const text = d.get_value("msg_content") || "";
                    const phone = data.clean_phone || "";
                    const url = phone ? `https://wa.me/${phone}?text=${encodeURIComponent(text)}` : `https://wa.me/?text=${encodeURIComponent(text)}`;
                    window.open(url, "_blank");
                }
            });

            d.set_secondary_action_label(__("Copy Message & Link 📋"));
            d.set_secondary_action(() => {
                const text = d.get_value("msg_content") || "";
                navigator.clipboard.writeText(text).then(() => {
                    frappe.show_alert({ message: __("Copied message & link to clipboard!"), indicator: "green" });
                });
            });

            d.show();

            d.$wrapper.find(".fd-wa-msg-type .fd-seg-btn").on("click", function () {
                d.$wrapper.find(".fd-wa-msg-type .fd-seg-btn").removeClass("active");
                $(this).addClass("active");
                activeType = $(this).data("type");
                if (msgs[activeType]) {
                    d.set_value("msg_content", msgs[activeType].text);
                }
            });
        }).catch((err) => {
            frappe.msgprint({ title: __("Error"), message: err.message || String(err), indicator: "red" });
        });
    },

    // ---------------- DAILY NIGHT AUDIT ----------------
    dialog_night_audit() {
        const me = this;
        FD.call("hospitality_core.api.audit.get_night_audit_summary", {}, {
            freeze: true,
            freeze_message: __("Calculating Night Audit metrics...")
        }).then((data) => {
            if (!data) return;

            const sym = data.currency_symbol || "£";

            const d = new frappe.ui.Dialog({
                title: __("Daily Night Audit & Owner Summary · {0}", [data.audit_date]),
                size: "large",
                fields: [
                    {
                        fieldtype: "HTML",
                        fieldname: "kpi_area",
                        options: `
                            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px;">
                                <div style="background:#eff6ff;border:1px solid #bfdbfe;padding:12px;border-radius:10px;text-align:center;">
                                    <div style="font-size:22px;font-weight:800;color:#1e40af;">${data.occupancy_pct}%</div>
                                    <div style="font-size:11px;font-weight:600;color:#3b82f6;text-transform:uppercase;">${__("Occupancy")} (${data.occupied_rooms}/${data.total_rooms})</div>
                                </div>
                                <div style="background:#ecfdf5;border:1px solid #a7f3d0;padding:12px;border-radius:10px;text-align:center;">
                                    <div style="font-size:22px;font-weight:800;color:#065f46;">${sym} ${flt(data.total_revenue).toFixed(2)}</div>
                                    <div style="font-size:11px;font-weight:600;color:#059669;text-transform:uppercase;">${__("Total Revenue")}</div>
                                </div>
                                <div style="background:#fefce8;border:1px solid #fde047;padding:12px;border-radius:10px;text-align:center;">
                                    <div style="font-size:22px;font-weight:800;color:#854d0e;">${sym} ${flt(data.adr).toFixed(2)}</div>
                                    <div style="font-size:11px;font-weight:600;color:#ca8a04;text-transform:uppercase;">${__("ADR (Avg Rate)")}</div>
                                </div>
                                <div style="background:#faf5ff;border:1px solid #e9d5ff;padding:12px;border-radius:10px;text-align:center;">
                                    <div style="font-size:22px;font-weight:800;color:#6b21a8;">${sym} ${flt(data.revpar).toFixed(2)}</div>
                                    <div style="font-size:11px;font-weight:600;color:#9333ea;text-transform:uppercase;">${__("RevPAR")}</div>
                                </div>
                            </div>
                            <div style="display:flex;gap:12px;background:#f8fafc;border:1px solid #e2e8f0;padding:10px 14px;border-radius:8px;margin-bottom:14px;font-size:12px;">
                                <span><b>${__("In-House:")}</b> ${data.in_house_count}</span> · 
                                <span><b>${__("Arrivals:")}</b> ${data.arrivals_today}</span> · 
                                <span><b>${__("Departures:")}</b> ${data.departures_today}</span> · 
                                <span><b>${__("Available Rooms:")}</b> ${data.available_rooms}</span> · 
                                <span><b>${__("Dirty Turnover:")}</b> ${data.dirty_rooms}</span>
                            </div>
                        `
                    },
                    {
                        fieldtype: "Small Text",
                        fieldname: "report_preview",
                        label: __("WhatsApp Executive Briefing (Ready to Send)"),
                        default: data.whatsapp_text || ""
                    }
                ],
                primary_action_label: __("Send WhatsApp to Owner 📱"),
                primary_action() {
                    const text = d.get_value("report_preview") || data.whatsapp_text;
                    const phone = data.owner_phone ? String(data.owner_phone).replace(/[^0-9]/g, "") : "";
                    const url = phone ? `https://wa.me/${phone}?text=${encodeURIComponent(text)}` : `https://wa.me/?text=${encodeURIComponent(text)}`;
                    window.open(url, "_blank");
                }
            });

            d.set_secondary_action_label(__("Run & Commit Audit ✅"));
            d.set_secondary_action(() => {
                FD.call("hospitality_core.api.audit.run_night_audit", { audit_date: data.audit_date }, {
                    freeze: true,
                    freeze_message: __("Posting Night Audit & logging to system...")
                }).then((r) => {
                    frappe.show_alert({ message: r.message || __("Audit completed!"), indicator: "green" });
                    d.hide();
                    me.load_data(true);
                });
            });

            d.show();
        }).catch((err) => {
            frappe.msgprint({ title: __("Night Audit Error"), message: err.message || String(err), indicator: "red" });
        });
    },

    // ---------------- OTA RESERVATION DETAILS & VOUCHER PRINT ----------------
    dialog_ota_details(name) {
        if (window.fd_dialog_ota_details) {
            window.fd_dialog_ota_details(name);
        } else {
            fd_open_doc_popup("OTA Reservation", name);
        }
    },

    // ---------------- PRINTABLE OTA VOUCHER FORMAT ----------------
    print_ota_voucher(doc, roomType, ratePlan) {
        const hotelName = frappe.boot.sysdefaults.company || frappe.defaults.get_default("company") || "Sky Hotel & Luxury Suites";
        const sym = doc.currency === "INR" ? "₹" : (doc.currency === "GBP" ? "£" : (doc.currency === "USD" ? "$" : (doc.currency === "EUR" ? "€" : (doc.currency ? doc.currency + " " : "₹ "))));
        const formatMoney = (val) => `${sym} ${frappe.format(val || 0, { fieldtype: "Currency" })}`;

        // Channel branding
        const ch = (doc.channel_name || "OTA").toLowerCase();
        let channelColor = "#0284c7";
        let channelTitle = doc.channel_name || "OTA";
        if (ch.includes("makemytrip") || ch.includes("mmt")) {
            channelColor = "#e11d48";
            channelTitle = "MakeMyTrip";
        } else if (ch.includes("booking")) {
            channelColor = "#003580";
            channelTitle = "Booking.com";
        } else if (ch.includes("airbnb")) {
            channelColor = "#ff385c";
            channelTitle = "Airbnb";
        } else if (ch.includes("expedia")) {
            channelColor = "#00355f";
            channelTitle = "Expedia";
        } else if (ch.includes("agoda")) {
            channelColor = "#2b3990";
            channelTitle = "Agoda";
        }

        const isAccepted = doc.status === "Accepted" || !!doc.hotel_reservation;
        const statusText = isAccepted ? "CONFIRMED & ACCEPTED" : (doc.status === "Cancelled" ? "CANCELLED" : "PENDING ACCEPTANCE");
        const statusColor = isAccepted ? "#16a34a" : (doc.status === "Cancelled" ? "#dc2626" : "#f59e0b");

        const voucherHtml = `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Booking Confirmation Voucher · ${doc.ota_booking_id || doc.name}</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            color: #0f172a;
            margin: 0;
            padding: 0;
            background: #f1f5f9;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }
        .no-print-bar {
            background: #1e293b;
            color: #ffffff;
            padding: 12px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            position: sticky;
            top: 0;
            z-index: 1000;
        }
        .no-print-bar button {
            cursor: pointer;
            border-radius: 6px;
            font-weight: 700;
            font-size: 13px;
            padding: 8px 18px;
            border: none;
            transition: all 0.2s;
        }
        .btn-print { background: #2563eb; color: #ffffff; }
        .btn-print:hover { background: #1d4ed8; }
        .btn-close { background: #475569; color: #ffffff; margin-left: 8px; }
        .btn-close:hover { background: #334155; }

        .voucher-sheet {
            max-width: 820px;
            margin: 24px auto;
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.06);
            padding: 36px 40px;
        }

        .header-wrap {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            border-bottom: 2px solid #0f172a;
            padding-bottom: 20px;
            margin-bottom: 24px;
        }
        .hotel-brand h1 {
            margin: 0;
            font-size: 26px;
            font-weight: 900;
            color: #0f172a;
            letter-spacing: -0.5px;
            text-transform: uppercase;
        }
        .hotel-brand .doc-type {
            font-size: 12px;
            font-weight: 800;
            letter-spacing: 1px;
            color: #475569;
            text-transform: uppercase;
            margin-top: 4px;
        }
        .channel-tag {
            display: inline-block;
            background: ${channelColor};
            color: #ffffff;
            font-size: 11px;
            font-weight: 800;
            padding: 4px 12px;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-top: 8px;
        }

        .ref-box {
            text-align: right;
        }
        .ref-number {
            font-size: 20px;
            font-weight: 900;
            color: #0f172a;
            letter-spacing: 0.5px;
        }
        .status-badge {
            display: inline-block;
            border: 2px solid ${statusColor};
            color: ${statusColor};
            font-size: 11px;
            font-weight: 900;
            padding: 3px 10px;
            border-radius: 4px;
            margin-top: 6px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .meta-text {
            font-size: 11px;
            color: #64748b;
            margin-top: 4px;
        }

        .section-header {
            font-size: 11px;
            font-weight: 900;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: #475569;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-left: 4px solid #0f172a;
            padding: 6px 12px;
            margin: 20px 0 12px;
        }

        .grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        .info-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            padding: 14px 16px;
        }
        .info-row {
            display: flex;
            justify-content: space-between;
            padding: 5px 0;
            font-size: 13px;
            border-bottom: 1px dashed #f1f5f9;
        }
        .info-row:last-child {
            border-bottom: none;
        }
        .info-lbl {
            color: #64748b;
            font-weight: 500;
        }
        .info-val {
            color: #0f172a;
            font-weight: 700;
            text-align: right;
        }

        .table-custom {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            margin-top: 6px;
        }
        .table-custom th, .table-custom td {
            border: 1px solid #cbd5e1;
            padding: 10px 14px;
        }
        .table-custom th {
            background: #f8fafc;
            font-weight: 800;
            color: #334155;
            text-align: left;
        }

        .notice-box {
            background: #fffbeb;
            border: 1px solid #fef3c7;
            border-radius: 6px;
            padding: 12px 14px;
            font-size: 12px;
            color: #92400e;
            margin-top: 14px;
        }

        .policy-list {
            font-size: 11px;
            color: #64748b;
            line-height: 1.6;
            margin: 12px 0 0;
            padding-left: 18px;
        }

        .sig-section {
            display: flex;
            justify-content: space-between;
            margin-top: 48px;
            page-break-inside: avoid;
        }
        .sig-block {
            width: 260px;
            text-align: center;
        }
        .sig-line {
            border-top: 1px solid #94a3b8;
            margin-bottom: 6px;
            padding-top: 6px;
            font-weight: 700;
            font-size: 12px;
            color: #334155;
        }
        .sig-sub {
            font-size: 10px;
            color: #94a3b8;
            text-transform: uppercase;
        }

        .footer-note {
            margin-top: 32px;
            border-top: 1px solid #e2e8f0;
            padding-top: 12px;
            font-size: 10px;
            color: #94a3b8;
            text-align: center;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        @media print {
            body { background: #ffffff; }
            .no-print-bar { display: none !important; }
            .voucher-sheet {
                max-width: 100%;
                margin: 0;
                padding: 15mm;
                border: none;
                box-shadow: none;
            }
            @page {
                size: A4 portrait;
                margin: 0;
            }
        }
    </style>
</head>
<body>
    <div class="no-print-bar">
        <div style="font-weight:700;font-size:14px;display:flex;align-items:center;gap:8px;">
            <span>🏨 Official Booking Voucher Preview</span>
            <span style="font-size:12px;font-weight:normal;color:#94a3b8;">· Click Print or press Ctrl+P</span>
        </div>
        <div>
            <button type="button" class="btn-print" onclick="window.print()">🖨️ Print Voucher</button>
            <button type="button" class="btn-close" onclick="window.close()">✕ Close</button>
        </div>
    </div>

    <div class="voucher-sheet">
        <!-- Header -->
        <div class="header-wrap">
            <div class="hotel-brand">
                <h1>${hotelName}</h1>
                <div class="doc-type">Official OTA Reservation Voucher & Guest Confirmation</div>
                <div class="channel-tag">${channelTitle} Partner Booking</div>
            </div>
            <div class="ref-box">
                <div class="ref-number">${doc.ota_booking_id || doc.name}</div>
                <div><span class="status-badge">${statusText}</span></div>
                ${doc.hotel_reservation ? `<div class="meta-text" style="color:#0284c7;font-weight:700;">Hotel Res: ${doc.hotel_reservation}</div>` : ""}
                <div class="meta-text">Issued: ${new Date().toLocaleString()}</div>
            </div>
        </div>

        <!-- 2 Columns: Guest & Stay Details -->
        <div class="grid-2">
            <div>
                <div class="section-header">👤 Guest Information</div>
                <div class="info-card">
                    <div class="info-row"><span class="info-lbl">Primary Guest:</span><span class="info-val">${doc.guest_name || "—"}</span></div>
                    <div class="info-row"><span class="info-lbl">Mobile Phone:</span><span class="info-val">${doc.guest_phone || "—"}</span></div>
                    <div class="info-row"><span class="info-lbl">Email Address:</span><span class="info-val">${doc.guest_email || "—"}</span></div>
                    <div class="info-row"><span class="info-lbl">Total Guests:</span><span class="info-val">${(parseInt(doc.adults, 10) || 1) + (parseInt(doc.children, 10) || 0)} Guests (${doc.adults || 1} Adult, ${doc.children || 0} Child)</span></div>
                </div>
            </div>

            <div>
                <div class="section-header">🏨 Stay & Room Information</div>
                <div class="info-card">
                    <div class="info-row"><span class="info-lbl">Check-In Date:</span><span class="info-val">${doc.check_in_date} (from 14:00)</span></div>
                    <div class="info-row"><span class="info-lbl">Check-Out Date:</span><span class="info-val">${doc.check_out_date} (by 11:00)</span></div>
                    <div class="info-row"><span class="info-lbl">Duration of Stay:</span><span class="info-val">${doc.nights || 1} Night(s)</span></div>
                    <div class="info-row"><span class="info-lbl">Room Category:</span><span class="info-val" style="color:#0284c7;">${roomType}</span></div>
                    <div class="info-row"><span class="info-lbl">Rate / Meal Plan:</span><span class="info-val">${ratePlan}</span></div>
                </div>
            </div>
        </div>

        <!-- Billing & Financial Breakdown -->
        <div class="section-header">💳 Tariff & Financial Settlement</div>
        <table class="table-custom">
            <thead>
                <tr>
                    <th>Description</th>
                    <th>Booking Channel</th>
                    <th>Payment Mode & Status</th>
                    <th style="text-align:right;">Total Amount</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>
                        <b>Room Accommodation Charges</b><br>
                        <span style="font-size:11px;color:#64748b;">${doc.nights || 1} Night(s) · ${roomType} (${ratePlan})</span>
                    </td>
                    <td><b>${channelTitle}</b></td>
                    <td>
                        <b>${doc.payment_collect || "OTA Collect"}</b><br>
                        <span style="font-size:11px;color:#16a34a;font-weight:700;">● ${doc.payment_status || "Paid Online"}</span>
                    </td>
                    <td style="text-align:right;font-size:16px;font-weight:900;color:#0f172a;">${formatMoney(doc.total_amount)}</td>
                </tr>
            </tbody>
        </table>

        ${doc.remarks ? `
        <!-- Special Requests -->
        <div class="notice-box">
            <b>📌 Special Requests / Remarks:</b> ${doc.remarks}
        </div>` : ""}

        <!-- Terms & Policies -->
        <div class="section-header">📜 Guest Stay Policies & House Rules</div>
        <ol class="policy-list">
            <li><b>Mandatory Identification:</b> Valid government-issued photo ID with residential address (Aadhaar, Passport, Driving License, Voter ID) is mandatory for all adult occupants upon check-in.</li>
            <li><b>Check-In & Check-Out:</b> Standard check-in time is 14:00 PM and check-out time is 11:00 AM. Early check-in or late check-out is subject to room availability and standard hotel tariff.</li>
            <li><b>Property House Rules:</b> All guest rooms are strictly non-smoking. Guests are liable for any damages to room furniture, equipment, or hotel fixtures during their stay.</li>
            <li><b>Settlement of Extras:</b> Incidental charges including room service, laundry, restaurant dining, or minibar usage must be settled directly with the reception prior to check-out.</li>
        </ol>

        <!-- Signature Section -->
        <div class="sig-section">
            <div class="sig-block">
                <div class="sig-line">Guest Signature</div>
                <div class="sig-sub">I accept the room allotment & hotel stay policies</div>
            </div>
            <div class="sig-block">
                <div class="sig-line">Front Desk Manager / Reception</div>
                <div class="sig-sub">Authorized Hotel Representative & Stamp</div>
            </div>
        </div>

        <!-- Footer -->
        <div class="footer-note">
            ${hotelName} · Official Computer-Generated Booking Voucher · Generated via Front Desk Console
        </div>
    </div>
</body>
</html>
        `;

        const printWindow = window.open("", "_blank");
        printWindow.document.write(voucherHtml);
        printWindow.document.close();
        setTimeout(() => {
            printWindow.focus();
            printWindow.print();
        }, 300);
    }
});

// Global accessor for standalone voucher printing
window.fd_print_ota_voucher = function(doc, roomType, ratePlan) {
    if (window.cur_fd_console && window.cur_fd_console.print_ota_voucher) {
        window.cur_fd_console.print_ota_voucher(doc, roomType, ratePlan);
    } else {
        FrontDeskConsole.prototype.print_ota_voucher(doc, roomType, ratePlan);
    }
};

// Global accessor for opening OTA Reservation Details & Voucher Modal
window.fd_dialog_ota_details = function(name) {
    if (!name) {
        frappe.msgprint({ title: __("Notice"), message: __("No reservation specified."), indicator: "orange" });
        return;
    }

    frappe.call({
        method: "frappe.client.get",
        args: { doctype: "OTA Reservation", name: name },
        freeze: true,
        freeze_message: __("Loading Booking Details..."),
        callback: (r) => {
            const doc = r.message;
            if (!doc) {
                frappe.msgprint({ title: __("Not Found"), message: __("Could not find OTA Reservation: {0}", [name]), indicator: "red" });
                return;
            }

            try {
                const isUuid = (s) => typeof s === "string" && s.trim().length === 36 && s.indexOf("-") !== -1;
                const roomType = (doc.room_type_name && !isUuid(doc.room_type_name)) ? doc.room_type_name : "Demo Double";
                const ratePlan = (doc.rate_plan_name && !isUuid(doc.rate_plan_name)) ? doc.rate_plan_name : "Standard Rate";

                const formatMoney = (val) => {
                    try {
                        return format_currency(val || 0, doc.currency || frappe.boot.sysdefaults.currency || "INR");
                    } catch (e) {
                        const sym = doc.currency === "INR" ? "₹" : (doc.currency === "GBP" ? "£" : (doc.currency === "USD" ? "$" : (doc.currency === "EUR" ? "€" : (doc.currency ? doc.currency + " " : "₹ "))));
                        return `${sym} ${(val || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                    }
                };

                // Channel theme colors & branding
                const ch = (doc.channel_name || "OTA").toLowerCase();
                let channelBg = "linear-gradient(135deg, #0284c7, #0369a1)";
                let channelTag = doc.channel_name || "OTA Channel";
                if (ch.includes("makemytrip") || ch.includes("mmt")) {
                    channelBg = "linear-gradient(135deg, #e11d48, #be123c)";
                    channelTag = "MakeMyTrip";
                } else if (ch.includes("booking")) {
                    channelBg = "linear-gradient(135deg, #003580, #00224f)";
                    channelTag = "Booking.com";
                } else if (ch.includes("airbnb")) {
                    channelBg = "linear-gradient(135deg, #ff385c, #e00b41)";
                    channelTag = "Airbnb";
                } else if (ch.includes("expedia")) {
                    channelBg = "linear-gradient(135deg, #00355f, #0c2340)";
                    channelTag = "Expedia";
                } else if (ch.includes("agoda")) {
                    channelBg = "linear-gradient(135deg, #2b3990, #1b2660)";
                    channelTag = "Agoda";
                } else if (ch.includes("goibibo")) {
                    channelBg = "linear-gradient(135deg, #ec5b24, #c94411)";
                    channelTag = "Goibibo";
                }

                // Status Badge
                const isAccepted = doc.status === "Accepted" || !!doc.hotel_reservation;
                const isCancelled = doc.status === "Cancelled";
                const statusHtml = isAccepted
                    ? `<span style="background:#dcfce7;color:#15803d;border:1px solid #86efac;font-weight:800;font-size:12px;padding:5px 12px;border-radius:20px;display:inline-flex;align-items:center;gap:5px;"><span>✓</span> ${__("Accepted & Confirmed")}</span>`
                    : (isCancelled
                        ? `<span style="background:#fee2e2;color:#b91c1c;border:1px solid #fca5a5;font-weight:800;font-size:12px;padding:5px 12px;border-radius:20px;display:inline-flex;align-items:center;gap:5px;"><span>✕</span> ${__("Cancelled")}</span>`
                        : `<span style="background:#fef3c7;color:#b45309;border:1px solid #fde68a;font-weight:800;font-size:12px;padding:5px 12px;border-radius:20px;display:inline-flex;align-items:center;gap:5px;"><span style="display:inline-block;width:8px;height:8px;background:#f59e0b;border-radius:50%;"></span> ${__("Pending Acceptance")}</span>`);

                // Format phone for WhatsApp
                const cleanPhone = (doc.guest_phone || "").replace(/[^0-9]/g, "");

                const html = `
                    <div class="fd-ota-voucher-modal" style="font-family:inherit;padding:2px 0;">
                        <!-- Header Banner -->
                        <div style="display:flex;justify-content:space-between;align-items:center;background:#f8fafc;border:1px solid #e2e8f0;padding:16px 20px;border-radius:12px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,0.05);">
                            <div style="display:flex;align-items:center;gap:14px;">
                                <div style="background:${channelBg};color:#ffffff;font-weight:800;font-size:13px;padding:8px 14px;border-radius:8px;text-transform:uppercase;letter-spacing:0.5px;box-shadow:0 2px 4px rgba(0,0,0,0.12);">
                                    ${FD.esc(channelTag)}
                                </div>
                                <div>
                                    <div style="display:flex;align-items:center;gap:8px;">
                                        <span style="font-size:18px;font-weight:800;color:#0f172a;letter-spacing:0.3px;">${FD.esc(doc.ota_booking_id || doc.name)}</span>
                                        <button type="button" class="btn btn-default btn-xs" style="padding:1px 6px;font-size:11px;" onclick="navigator.clipboard.writeText('${doc.ota_booking_id || doc.name}'); frappe.show_alert({message: __('Booking ID Copied!'), indicator: 'green'});" title="${__("Copy Booking ID")}">📋</button>
                                    </div>
                                    <div style="font-size:12px;color:#64748b;margin-top:2px;">
                                        ${__("Received via Channel Manager")}: <b>${frappe.datetime.str_to_user(doc.received_at || doc.creation)}</b>
                                    </div>
                                </div>
                            </div>
                            <div style="text-align:right;">
                                ${statusHtml}
                                ${doc.hotel_reservation ? `
                                    <div style="margin-top:6px;font-size:12px;font-weight:700;color:#0284c7;">
                                        ${__("Hotel Reservation")}: <a href="/app/hotel-reservation/${encodeURIComponent(doc.hotel_reservation)}" target="_blank" style="text-decoration:underline;color:#0284c7;">${FD.esc(doc.hotel_reservation)}</a>
                                    </div>` : ""}
                            </div>
                        </div>

                        <!-- 2 Grid Cards: Guest & Stay Details -->
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;">
                            <!-- Guest Information -->
                            <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:16px 18px;box-shadow:0 1px 2px rgba(0,0,0,0.03);">
                                <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9;padding-bottom:10px;margin-bottom:12px;">
                                    <span style="font-size:12px;font-weight:800;color:#475569;text-transform:uppercase;letter-spacing:0.6px;">👤 ${__("Guest Information")}</span>
                                    <span style="background:#e0f2fe;color:#0369a1;font-size:11px;font-weight:700;padding:2px 8px;border-radius:10px;">${doc.adults || 1} Adult(s)${doc.children ? `, ${doc.children} Child(ren)` : ""}</span>
                                </div>
                                <div style="display:flex;flex-direction:column;gap:10px;font-size:13px;">
                                    <div style="display:flex;justify-content:space-between;align-items:center;">
                                        <span style="color:#64748b;">${__("Primary Guest")}:</span>
                                        <b style="color:#0f172a;font-size:14px;">${FD.esc(doc.guest_name || "—")}</b>
                                    </div>
                                    <div style="display:flex;justify-content:space-between;align-items:center;">
                                        <span style="color:#64748b;">${__("Mobile Phone")}:</span>
                                        <div style="display:flex;align-items:center;gap:6px;">
                                            <b style="color:#0f172a;">${FD.esc(doc.guest_phone || "—")}</b>
                                            ${cleanPhone ? `<a href="https://wa.me/${cleanPhone}" target="_blank" class="btn btn-default btn-xs" style="color:#16a34a;font-weight:700;padding:0 5px;" title="${__("Open WhatsApp Chat")}">WA</a>` : ""}
                                        </div>
                                    </div>
                                    <div style="display:flex;justify-content:space-between;align-items:center;">
                                        <span style="color:#64748b;">${__("Email Address")}:</span>
                                        <span style="color:#334155;font-weight:600;max-width:210px;text-overflow:ellipsis;overflow:hidden;white-space:nowrap;" title="${FD.esc(doc.guest_email || '')}">${FD.esc(doc.guest_email || "—")}</span>
                                    </div>
                                    <div style="display:flex;justify-content:space-between;align-items:center;">
                                        <span style="color:#64748b;">${__("Total Occupancy")}:</span>
                                        <b style="color:#0f172a;">${(parseInt(doc.adults, 10) || 1) + (parseInt(doc.children, 10) || 0)} ${__("Guests")} (${doc.adults || 1}A, ${doc.children || 0}C)</b>
                                    </div>
                                </div>
                            </div>

                            <!-- Stay Details -->
                            <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:16px 18px;box-shadow:0 1px 2px rgba(0,0,0,0.03);">
                                <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #f1f5f9;padding-bottom:10px;margin-bottom:12px;">
                                    <span style="font-size:12px;font-weight:800;color:#475569;text-transform:uppercase;letter-spacing:0.6px;">🏨 ${__("Stay & Room Details")}</span>
                                    <span style="background:#f1f5f9;color:#334155;font-size:11px;font-weight:800;padding:2px 8px;border-radius:10px;">${doc.nights || 1} ${__("Night(s)")}</span>
                                </div>
                                <div style="display:flex;flex-direction:column;gap:10px;font-size:13px;">
                                    <div style="display:flex;justify-content:space-between;align-items:center;">
                                        <span style="color:#64748b;">${__("Check-In")}:</span>
                                        <b style="color:#0f172a;">${FD.date(doc.check_in_date)} <span style="font-size:11px;font-weight:normal;color:#64748b;">(from 14:00)</span></b>
                                    </div>
                                    <div style="display:flex;justify-content:space-between;align-items:center;">
                                        <span style="color:#64748b;">${__("Check-Out")}:</span>
                                        <b style="color:#0f172a;">${FD.date(doc.check_out_date)} <span style="font-size:11px;font-weight:normal;color:#64748b;">(by 11:00)</span></b>
                                    </div>
                                    <div style="display:flex;justify-content:space-between;align-items:center;">
                                        <span style="color:#64748b;">${__("Room Category")}:</span>
                                        <b style="color:#0284c7;font-weight:800;">${FD.esc(roomType)}</b>
                                    </div>
                                    <div style="display:flex;justify-content:space-between;align-items:center;">
                                        <span style="color:#64748b;">${__("Rate / Meal Plan")}:</span>
                                        <span style="background:#f8fafc;border:1px solid #e2e8f0;padding:2px 8px;border-radius:6px;font-weight:700;font-size:12px;color:#334155;">${FD.esc(ratePlan)}</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Financial & Payout Summary Card -->
                        <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:16px 18px;margin-bottom:16px;box-shadow:0 1px 2px rgba(0,0,0,0.03);">
                            <div style="font-size:12px;font-weight:800;color:#475569;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">
                                💳 ${__("Financial Settlement & Tariff Breakdown")}
                            </div>
                            <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:14px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;">
                                <div>
                                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:700;letter-spacing:0.3px;">${__("Total Booking Amount")}</div>
                                    <div style="font-size:19px;font-weight:900;color:#0f172a;margin-top:3px;">${formatMoney(doc.total_amount)}</div>
                                </div>
                                <div>
                                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:700;letter-spacing:0.3px;">${__("OTA Commission")}</div>
                                    <div style="font-size:16px;font-weight:800;color:#dc2626;margin-top:4px;">${formatMoney(doc.commission)}</div>
                                </div>
                                <div>
                                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:700;letter-spacing:0.3px;">${__("Net Hotel Payout")}</div>
                                    <div style="font-size:16px;font-weight:800;color:#16a34a;margin-top:4px;">${formatMoney((doc.total_amount || 0) - (doc.commission || 0))}</div>
                                </div>
                                <div>
                                    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:700;letter-spacing:0.3px;">${__("Collection & Status")}</div>
                                    <div style="font-size:13px;font-weight:800;color:#1e293b;margin-top:2px;">${FD.esc(doc.payment_collect || "OTA Collect")}</div>
                                    <div style="font-size:11px;font-weight:700;color:#16a34a;margin-top:2px;">● ${FD.esc(doc.payment_status || "Paid Online")}</div>
                                </div>
                            </div>
                        </div>

                        ${doc.remarks ? `
                        <!-- Special Requests -->
                        <div style="background:#fffbeb;border:1px solid #fef3c7;border-radius:10px;padding:12px 16px;font-size:13px;color:#92400e;margin-bottom:16px;">
                            <b style="display:inline-block;margin-bottom:4px;">📌 ${__("Guest Special Requests / Notes")}:</b>
                            <div>${FD.esc(doc.remarks)}</div>
                        </div>` : ""}

                        <!-- Raw JSON Payload Accordion (Collapsed) -->
                        <details style="margin-top:8px;font-size:12px;color:#64748b;border-top:1px dashed #e2e8f0;padding-top:10px;">
                            <summary style="cursor:pointer;font-weight:600;padding:4px 0;user-select:none;">
                                🔍 ${__("Technical Channel Payload (Channex Raw JSON)")}
                            </summary>
                            <pre style="background:#0f172a;color:#f8fafc;padding:12px 14px;border-radius:8px;max-height:160px;overflow:auto;margin-top:8px;font-size:11px;line-height:1.45;">${FD.esc(doc.raw_payload || "{}")}</pre>
                        </details>
                    </div>
                `;

                const d = new frappe.ui.Dialog({
                    title: `${channelTag} · ${doc.ota_booking_id || doc.name}`,
                    size: "large",
                    fields: [{ fieldtype: "HTML", fieldname: "body", options: html }]
                });

                d.show();
                if (d.get_field("body") && d.get_field("body").$wrapper) {
                    d.get_field("body").$wrapper.html(html);
                }

                // Print Voucher Action
                d.set_secondary_action_label(`🖨️ ${__("Print Booking Voucher")}`);
                d.set_secondary_action(() => {
                    window.fd_print_ota_voucher(doc, roomType, ratePlan);
                });

                // Primary Workflow Action
                if (!isAccepted && !isCancelled) {
                    d.set_primary_action_label(`⚡ ${__("Accept Booking")}`);
                    d.set_primary_action(() => {
                        d.hide();
                        FD.call("hospitality_core.api.console.accept_ota_booking", {
                            ota_reservation_name: doc.name
                        }, { freeze: true, freeze_message: __("Accepting booking & creating Hotel Reservation...") })
                            .then((res) => {
                                frappe.show_alert({ message: __("Accepted! Created Hotel Reservation {0}", [res.reservation]), indicator: "green" });
                                if (window.cur_fd_console && window.cur_fd_console.load_data) {
                                    window.cur_fd_console.load_data(true);
                                }
                            })
                            .catch((err) => {
                                frappe.msgprint({ title: __("Accept Failed"), message: err.message || String(err), indicator: "red" });
                            });
                    });
                } else if (doc.hotel_reservation) {
                    d.set_primary_action_label(`🛎️ ${__("View Hotel Reservation")}`);
                    d.set_primary_action(() => {
                        d.hide();
                        if (window.cur_fd_console && window.cur_fd_console.dialog_reservation) {
                            window.cur_fd_console.dialog_reservation(doc.hotel_reservation);
                        } else {
                            frappe.set_route("Form", "Hotel Reservation", doc.hotel_reservation);
                        }
                    });
                }
            } catch (err) {
                console.error("[FrontDesk] Voucher error:", err);
                frappe.msgprint({
                    title: __("Voucher Display Error"),
                    message: __("Failed to render voucher: {0}", [err.message || String(err)]),
                    indicator: "red"
                });
            }
        },
        error: (err) => {
            console.error("[FrontDesk] Fetch error:", err);
            frappe.msgprint({
                title: __("Server Error"),
                message: __("Failed to load OTA Reservation from server."),
                indicator: "red"
            });
        }
    });
};
