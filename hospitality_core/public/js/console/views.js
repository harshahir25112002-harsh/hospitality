/**
 * Front Desk Console - tab views. Mixed into FrontDeskConsole.prototype.
 */
Object.assign(FrontDeskConsole.prototype, {

    // ---------------- ROOM BOARD ----------------
    render_room_board($tab) {
        const me = this;
        const s = this.state;
        const f = this.filters;
        const opt = (list, cur, all) => `<option value="">${all}</option>` +
            list.map((v) => `<option value="${FD.esc(v)}" ${String(v) === String(cur) ? "selected" : ""}>${FD.esc(v)}</option>`).join("");

        $tab.html(`
            <div class="fd-toolbar">
                <select class="form-control input-sm fd-f-floor">${opt(s.floors || [], f.floor, __("All Floors"))}</select>
                <select class="form-control input-sm fd-f-type">${opt(s.room_types || [], f.room_type, __("All Room Types"))}</select>
                <select class="form-control input-sm fd-f-status">${opt(Object.keys(FD.STATUS), f.status, __("All Statuses"))}</select>
                <input class="form-control input-sm fd-f-text" placeholder="${__("Filter rooms / guests")}" value="${FD.esc(f.text)}">
                <div class="fd-legend">${Object.keys(FD.STATUS).map((k) => FD.room_pill(k)).join("")}</div>
            </div>
            <div class="fd-board"></div>`);

        const draw = () => {
            const text = (f.text || "").toLowerCase();
            const rooms = (s.rooms || []).filter((r) =>
                (!f.floor || String(r.floor) === String(f.floor)) &&
                (!f.room_type || r.room_type === f.room_type) &&
                (!f.status || r.status === f.status) &&
                (!text || [r.room_number, r.name, r.guest_name, r.room_type, r.reservation].join(" ").toLowerCase().includes(text))
            );
            const $b = $tab.find(".fd-board");
            if (!s.rooms.length) { $b.html(FD.empty(__("No rooms configured yet."), "bed-double")); return; }
            if (!rooms.length) { $b.html(FD.empty(__("No rooms match the filters."), "search")); return; }

            const by_floor = {};
            rooms.forEach((r) => { (by_floor[r.floor || __("No Floor")] = by_floor[r.floor || __("No Floor")] || []).push(r); });
            $b.html(Object.keys(by_floor).sort().map((fl) => `
                <div class="fd-floor">
                    <div class="fd-floor-title">${__("Floor")} ${FD.esc(fl)} <span class="text-muted">· ${by_floor[fl].length}</span></div>
                    <div class="fd-room-grid">${by_floor[fl].map((r) => me.room_card(r)).join("")}</div>
                </div>`).join(""));
        };
        draw();

        $tab.find(".fd-f-floor").on("change", function () { f.floor = $(this).val(); draw(); });
        $tab.find(".fd-f-type").on("change", function () { f.room_type = $(this).val(); draw(); });
        $tab.find(".fd-f-status").on("change", function () { f.status = $(this).val(); draw(); });
        $tab.find(".fd-f-text").on("input", frappe.utils.debounce(function () { f.text = $(this).val(); draw(); }, 200));
        $tab.on("click", ".fd-room-card", function () {
            const room = s.rooms.find((r) => r.name === $(this).data("room"));
            if (room) me.show_room_dialog(room);
        });
    },

    room_card(r) {
        const st = FD.STATUS[r.status] || FD.STATUS.Available;
        const guest = r.guest_name ? `
            <div class="fd-rc-guest">${FD.icon("user")}<span>${FD.esc(r.guest_name)}</span></div>
            <div class="fd-rc-dates">${FD.date(r.check_in_date)} → ${FD.date(r.check_out_date)}</div>` : "";
        const money = [];
        if (r.balance > 0) money.push(`<span class="fd-rc-due">${__("Due")} ${FD.money(r.balance)}</span>`);
        if (r.room_service_pending > 0) money.push(`<span class="fd-rc-rs">${FD.icon("bell")} ${FD.money(r.room_service_pending)}</span>`);
        return `
            <div class="fd-room-card fd-st-${st.cls}" data-room="${FD.esc(r.name)}" tabindex="0" role="button">
                <div class="fd-rc-top">
                    <span class="fd-rc-num">${FD.esc(r.room_number || r.name)}</span>
                    ${FD.room_pill(r.status)}
                </div>
                <div class="fd-rc-type">${FD.esc(r.room_type)}${r.floor ? ` · ${__("Floor")} ${FD.esc(r.floor)}` : ""}</div>
                ${guest}
                ${money.length ? `<div class="fd-rc-money">${money.join("")}</div>` : ""}
            </div>`;
    },

    // ---------------- LIST TABLES ----------------
    render_table($tab, rows, cols, actions, empty_msg) {
        if (!rows.length) { $tab.html(FD.empty(empty_msg, "inbox")); return; }
        $tab.html(`
            <div class="fd-table-wrap"><table class="fd-table">
                <thead><tr>${cols.map((c) => `<th class="${c.cls || ""}">${c.label}</th>`).join("")}<th></th></tr></thead>
                <tbody>${rows.map((r) => `
                    <tr data-res="${FD.esc(r.name)}">
                        ${cols.map((c) => `<td class="${c.cls || ""}" data-label="${FD.esc(c.label)}">${c.render(r)}</td>`).join("")}
                        <td class="fd-row-actions">${actions(r)}</td>
                    </tr>`).join("")}
                </tbody>
            </table></div>`);
    },

    common_cols() {
        return [
            { label: __("Guest"), render: (r) => `<b>${FD.esc(r.guest_name || r.customer)}</b><div class="text-muted small">${FD.esc(r.name)}</div>` },
            { label: __("Room"), render: (r) => `${FD.esc(r.room || __("Not Assigned"))}<div class="text-muted small">${FD.esc(r.room_type)}</div>` },
            { label: __("Stay"), render: (r) => `${FD.date(r.check_in_date)} → ${FD.date(r.check_out_date)}` },
        ];
    },

    bind_row_actions($tab) {
        const me = this;
        $tab.on("click", "[data-act]", function (e) {
            e.stopPropagation();
            const act = $(this).data("act");
            const res = $(this).closest("[data-res]").data("res");
            const map = {
                view: () => me.dialog_reservation(res),
                checkin: () => me.dialog_checkin(res),
                change_room: () => me.dialog_change_reserved_room(res),
                cancel: () => me.dialog_cancel(res),
                pay: () => me.dialog_receive_payment(res),
                pos: () => me.open_room_service_for(res),
                move: () => me.dialog_move_room(res),
                extend: () => me.dialog_extend_stay(res),
                bill: () => me.dialog_bill_preview(res),
                checkout: () => me.dialog_checkout(res),
            };
            map[act] && map[act]();
        });
        $tab.on("click", "tbody tr", function (e) {
            if ($(e.target).closest("button, a").length) return;
            me.dialog_reservation($(this).data("res"));
        });
    },

    btn(act, label, cls = "btn-default") {
        return `<button class="btn btn-xs ${cls}" data-act="${act}">${label}</button>`;
    },

    render_arrivals($tab) {
        const b = this.btn.bind(this);
        this.render_table($tab, this.state.arrivals, [
            ...this.common_cols(),
            { label: __("Status"), render: (r) => FD.pill(r.status) },
            { label: __("Paid"), cls: "text-right", render: (r) => FD.money(r.total_paid) },
        ], () => b("checkin", __("Check In"), "btn-primary") + b("view", __("View")) + b("cancel", __("Cancel"), "btn-danger-light"),
        __("No arrivals expected on {0}", [FD.date(this.current_date)]));
        this.bind_row_actions($tab);
    },

    render_in_house($tab) {
        const b = this.btn.bind(this);
        this.render_table($tab, this.state.in_house, [
            ...this.common_cols(),
            { label: __("Room Service"), cls: "text-right", render: (r) => r.room_service_pending > 0 ? `<span class="text-warning">${FD.money(r.room_service_pending)}</span>` : "—" },
            { label: __("Balance"), cls: "text-right", render: (r) => r.balance > 0 ? `<b class="text-danger">${FD.money(r.balance)}</b>` : `<span class="text-success">${FD.money(r.balance)}</span>` },
        ], () => b("pay", __("Payment"), "btn-primary") + b("pos", __("Room Order")) + b("move", __("Move")) + b("extend", __("Extend")) + b("bill", __("Bill")) + b("checkout", __("Check Out"), "btn-dark"),
        __("No guests are currently checked in."));
        this.bind_row_actions($tab);
    },

    render_departures($tab) {
        const b = this.btn.bind(this);
        this.render_table($tab, this.state.departures, [
            ...this.common_cols(),
            { label: __("Payment"), render: (r) => r.balance > 0 ? `<span class="indicator-pill red">${__("Due")} ${FD.money(r.balance)}</span>` : `<span class="indicator-pill green">${__("Settled")}</span>` },
            { label: __("Status"), render: (r) => FD.pill(r.status) },
        ], () => b("bill", __("Bill Preview")) + b("pay", __("Payment")) + b("checkout", __("Check Out"), "btn-dark"),
        __("No departures due on {0}", [FD.date(this.current_date)]));
        this.bind_row_actions($tab);
    },

    // ---------------- RESERVATIONS ----------------
    render_reservations($tab) {
        const me = this;
        const f = this.res_filters;
        const statuses = ["Upcoming", "Reserved", "Checked In", "Checked Out", "Cancelled", ""];
        $tab.html(`
            <div class="fd-toolbar">
                <div class="fd-seg">${statuses.map((s) => `<button class="fd-seg-btn ${f.status === s ? "active" : ""}" data-st="${s}">${s ? __(s) : __("All")}</button>`).join("")}</div>
                <input class="form-control input-sm fd-r-text" placeholder="${__("Search guest, room, reservation")}" value="${FD.esc(f.text)}">
                <button class="btn btn-primary btn-sm fd-r-new">${FD.icon("plus")} ${__("New")}</button>
            </div>
            <div class="fd-r-list">${FD.skeleton(4)}</div>`);
        const load = () => {
            FD.call("hospitality_core.api.console.get_reservations", { status: f.status, text: f.text }).then((rows) => {
                const $l = $tab.find(".fd-r-list");
                const b = me.btn.bind(me);
                me.render_table($l, rows || [], [
                    ...me.common_cols(),
                    { label: __("Status"), render: (r) => FD.pill(r.status) },
                    { label: __("Balance"), cls: "text-right", render: (r) => ["Reserved", "Checked In"].includes(r.status) ? FD.money(r.balance) : "—" },
                ], (r) => {
                    if (r.status === "Reserved") return b("checkin", __("Check In"), "btn-primary") + b("cancel", __("Cancel"), "btn-danger-light");
                    if (r.status === "Checked In") return b("bill", __("Bill")) + b("checkout", __("Check Out"), "btn-dark");
                    return b("view", __("View"));
                }, __("No reservations found."));
            });
        };
        $tab.find(".fd-seg-btn").on("click", function () { f.status = $(this).data("st"); me.render_reservations($tab.empty().off()); });
        $tab.find(".fd-r-text").on("input", frappe.utils.debounce(function () { f.text = $(this).val(); load(); }, 300));
        $tab.find(".fd-r-new").on("click", () => me.dialog_new_reservation());
        this.bind_row_actions($tab);
        load();
    },


    // ---------------- OTA BOOKINGS ----------------
    render_ota_bookings($tab) {
        const me = this;
        this.ota_filters = this.ota_filters || { status: "", text: "" };
        const f = this.ota_filters;
        const statuses = ["", "New", "Confirmed", "Modified", "Cancelled"];
        $tab.html(`
            <div class="fd-toolbar">
                <div class="fd-seg">${statuses.map((s) => `<button class="fd-seg-btn fd-ota-seg-btn ${f.status === s ? "active" : ""}" data-st="${s}">${s ? __(s) : __("All")}</button>`).join("")}</div>
                <input class="form-control input-sm fd-ota-text" placeholder="${__("Search guest, OTA ID, channel, room...")}" value="${FD.esc(f.text)}">
                <button class="btn btn-default btn-sm fd-ota-fetch">${FD.icon("refresh-cw")} ${__("Fetch Bookings Now")}</button>
                <button class="btn btn-default btn-sm fd-ota-settings">${FD.icon("settings")} ${__("OTA Settings")}</button>
            </div>
            <div class="fd-ota-list">${FD.skeleton(4)}</div>`);

        const load = () => {
            FD.call("hospitality_core.api.console.get_ota_bookings", { status: f.status, text: f.text }).then((rows) => {
                const $l = $tab.find(".fd-ota-list");
                if (!rows || !rows.length) {
                    $l.html(FD.empty(__("No OTA bookings found. Click 'Fetch Bookings Now' to check for new bookings."), "globe"));
                    return;
                }
                const statusColors = {
                    "New": "blue",
                    "Confirmed": "green",
                    "Modified": "yellow",
                    "Cancelled": "red"
                };
                const cols = [
                    { label: __("OTA Ref / Channel"), render: (r) => `<b>${FD.esc(r.ota_booking_id || r.name)}</b><div><span class="badge" style="font-size:10px;background:#0284c7;color:#fff">${FD.esc(r.channel_name || "OTA")}</span></div>` },
                    { label: __("Guest"), render: (r) => `<b>${FD.esc(r.guest_name || __("OTA Guest"))}</b><div class="text-muted small">${FD.esc(r.guest_phone || r.guest_email || "")}</div>` },
                    { label: __("Stay"), render: (r) => `${FD.date(r.check_in_date)} → ${FD.date(r.check_out_date)}<div class="text-muted small">${r.nights || 1} ${__("night(s)")}</div>` },
                    { label: __("Room / Rate"), render: (r) => `<b>${FD.esc(r.room_type_name || "—")}</b><div class="text-muted small">${FD.esc(r.rate_plan_name || "")}</div>` },
                    { label: __("Amount"), cls: "text-right", render: (r) => `<b>${r.currency || "INR"} ${format_currency(r.total_amount || 0)}</b><div class="text-muted small">${r.payment_status || ""}</div>` },
                    { label: __("Status"), render: (r) => `<span class="indicator-pill ${statusColors[r.status] || "gray"}">${FD.esc(__(r.status || "New"))}</span>` },
                    { label: __("Received"), render: (r) => `<span class="text-muted small">${r.received_at ? frappe.datetime.str_to_user(r.received_at) : "—"}</span>` },
                ];
                $l.html(`
                    <div class="fd-table-wrap"><table class="fd-table">
                        <thead><tr>${cols.map((c) => `<th class="${c.cls || ""}">${c.label}</th>`).join("")}<th></th></tr></thead>
                        <tbody>${rows.map((r) => `
                            <tr data-name="${FD.esc(r.name)}" class="fd-ota-row" style="cursor:pointer">
                                ${cols.map((c) => `<td class="${c.cls || ""}">${c.render(r)}</td>`).join("")}
                                <td class="fd-row-actions">
                                    <button class="btn btn-default btn-xs fd-ota-view" data-name="${FD.esc(r.name)}">${FD.icon("eye")} <span>${__("View")}</span></button>
                                </td>
                            </tr>`).join("")}
                        </tbody>
                    </table></div>`);
            });
        };

        $tab.find(".fd-ota-seg-btn").on("click", function () {
            f.status = $(this).data("st");
            me.render_ota_bookings($tab.empty().off());
        });
        $tab.find(".fd-ota-text").on("input", frappe.utils.debounce(function () {
            f.text = $(this).val();
            load();
        }, 300));
        $tab.find(".fd-ota-fetch").on("click", (e) => {
            FD.call("hospitality_core.api.ota.pull_booking_revisions", {}, { btn: e.currentTarget, freeze: true, freeze_message: __("Fetching bookings from OTA...") })
                .then((r) => {
                    frappe.show_alert({
                        message: __("Fetched {0} new/updated bookings!", [r.processed || 0]),
                        indicator: "green"
                    });
                    load();
                })
                .catch((err) => {
                    frappe.msgprint({ title: __("Sync Error"), message: err.message || __("Failed to fetch bookings. Check OTA Settings."), indicator: "red" });
                });
        });
        $tab.find(".fd-ota-settings").on("click", () => {
            frappe.set_route("Form", "OTA Settings");
        });
        $tab.on("click", ".fd-ota-row, .fd-ota-view", function (e) {
            e.stopPropagation();
            const name = $(this).data("name") || $(this).closest("tr").data("name");
            if (name) fd_open_doc_popup("OTA Reservation", name);
        });

        load();
    },

    // ---------------- TAPE CHART ----------------
    render_tape_chart($tab) {
        const me = this;
        this.tc_start = this.tc_start || frappe.datetime.add_days(this.current_date, -1);
        const days = this.tc_days || 14;
        $tab.html(`
            <div class="fd-toolbar">
                <button class="btn btn-default btn-sm fd-icon-btn fd-tc-prev">${FD.icon("chevron-left")}</button>
                <button class="btn btn-default btn-sm fd-tc-today">${__("Today")}</button>
                <button class="btn btn-default btn-sm fd-icon-btn fd-tc-next">${FD.icon("chevron-right")}</button>
                <select class="form-control input-sm fd-tc-days" style="max-width:120px">
                    ${[7, 14, 21, 30].map((d) => `<option value="${d}" ${d === days ? "selected" : ""}>${d} ${__("days")}</option>`).join("")}
                </select>
                <div class="fd-legend"><span class="fd-tc-legend reserved">${__("Reserved")}</span><span class="fd-tc-legend checkedin">${__("Checked In")}</span></div>
            </div>
            <div class="fd-tc-wrap">${FD.skeleton(3)}</div>`);
        const shift = (n) => { me.tc_start = frappe.datetime.add_days(me.tc_start, n); me.render_tape_chart($tab.empty().off()); };
        $tab.find(".fd-tc-prev").on("click", () => shift(-7));
        $tab.find(".fd-tc-next").on("click", () => shift(7));
        $tab.find(".fd-tc-today").on("click", () => { me.tc_start = frappe.datetime.add_days(frappe.datetime.get_today(), -1); me.render_tape_chart($tab.empty().off()); });
        $tab.find(".fd-tc-days").on("change", function () { me.tc_days = parseInt($(this).val()); me.render_tape_chart($tab.empty().off()); });

        const end = frappe.datetime.add_days(this.tc_start, days);
        FD.call("hospitality_core.hospitality_core.page.tape_chart.tape_chart.get_chart_data", { start_date: this.tc_start, end_date: end })
            .then((data) => {
                const dates = Array.from({ length: days }, (_, i) => frappe.datetime.add_days(me.tc_start, i));
                const today = frappe.datetime.get_today();
                const col_w = 64;
                const head = dates.map((d) => {
                    const m = moment(d);
                    return `<div class="fd-tc-day ${d === today ? "today" : ""} ${[0, 6].includes(m.day()) ? "weekend" : ""}" style="width:${col_w}px">
                        <div>${m.format("ddd")}</div><b>${m.format("DD")}</b><div>${m.format("MMM")}</div></div>`;
                }).join("");
                const by_room = {};
                (data.bookings || []).forEach((b) => (by_room[b.room] = by_room[b.room] || []).push(b));
                const rows = (data.rooms || []).map((r) => {
                    const blocks = (by_room[r.name] || []).map((b) => {
                        const from = moment.max(moment(b.arrival_date), moment(me.tc_start));
                        const to = moment.min(moment(b.departure_date || end), moment(end));
                        const left = from.diff(moment(me.tc_start), "days") * col_w;
                        const width = Math.max(to.diff(from, "days"), 1) * col_w - 4;
                        const cls = b.status === "Checked In" ? "checkedin" : "reserved";
                        return `<div class="fd-tc-block ${cls}" data-res="${FD.esc(b.name)}" style="left:${left + 2}px;width:${width}px"
                            title="${FD.esc(b.guest || "")} · ${FD.esc(b.name)}">${FD.esc(b.guest || b.name)}</div>`;
                    }).join("");
                    const cells = dates.map((d) => `<div class="fd-tc-cell ${d === today ? "today" : ""}" data-date="${d}" style="width:${col_w}px"></div>`).join("");
                    return `<div class="fd-tc-row" data-room="${FD.esc(r.name)}" data-type="${FD.esc(r.room_type)}">
                        <div class="fd-tc-room"><b>${FD.esc(r.room_number || r.name)}</b><span>${FD.esc(r.room_type)}</span>${FD.room_pill(r.status)}</div>
                        <div class="fd-tc-track" style="width:${days * col_w}px">${cells}${blocks}</div>
                    </div>`;
                }).join("");
                $tab.find(".fd-tc-wrap").html(data.rooms && data.rooms.length ? `
                    <div class="fd-tc">
                        <div class="fd-tc-row fd-tc-head"><div class="fd-tc-room">${__("Room")}</div><div class="fd-tc-track" style="width:${days * col_w}px">${head}</div></div>
                        ${rows}
                    </div>` : FD.empty(__("No rooms configured yet."), "bed-double"));
                $tab.find(".fd-tc-block").on("click", function (e) { e.stopPropagation(); me.dialog_reservation($(this).data("res")); });
                $tab.find(".fd-tc-cell").on("click", function () {
                    const $row = $(this).closest(".fd-tc-row");
                    me.dialog_new_reservation($row.data("room"), $row.data("type"), $(this).data("date"));
                });
            });
    },

    // ---------------- HOUSEKEEPING ----------------
    render_housekeeping($tab) {
        const me = this;
        const s = this.state;
        this.hk_filter = this.hk_filter || { floor: "", status: "Dirty", text: "" };
        const f = this.hk_filter;
        $tab.html(`
            <div class="fd-toolbar">
                <div class="fd-seg">${["Dirty", "Available", "Occupied", "Out of Order", ""].map((st) =>
                    `<button class="fd-seg-btn ${f.status === st ? "active" : ""}" data-st="${st}">${st ? __(st) : __("All")}</button>`).join("")}</div>
                <select class="form-control input-sm fd-hk-floor" style="max-width:150px"><option value="">${__("All Floors")}</option>
                    ${(s.floors || []).map((fl) => `<option ${String(fl) === String(f.floor) ? "selected" : ""}>${FD.esc(fl)}</option>`).join("")}</select>
                <input class="form-control input-sm fd-hk-text" placeholder="${__("Room number")}" value="${FD.esc(f.text)}">
            </div>
            <div class="fd-hk-grid"></div>`);
        const draw = () => {
            const rooms = s.rooms.filter((r) => (!f.status || r.status === f.status) && (!f.floor || String(r.floor) === String(f.floor)) &&
                (!f.text || String(r.room_number || r.name).toLowerCase().includes(f.text.toLowerCase())));
            const $g = $tab.find(".fd-hk-grid");
            if (!rooms.length) { $g.html(FD.empty(f.status === "Dirty" ? __("All rooms are clean.") : __("No rooms."), "sparkles")); return; }
            $g.html(`<div class="fd-room-grid">${rooms.map((r) => {
                const st = FD.STATUS[r.status] || FD.STATUS.Available;
                let action = "";
                if (r.status === "Dirty") action = `<button class="btn btn-success btn-sm btn-block fd-hk-act" data-act="Clean" data-room="${FD.esc(r.name)}">${FD.icon("sparkles")} ${__("Mark Clean")}</button>`;
                else if (r.status === "Available") action = `<button class="btn btn-default btn-sm btn-block fd-hk-act" data-act="Dirty" data-room="${FD.esc(r.name)}">${__("Mark Dirty")}</button>`;
                else if (r.status === "Occupied") action = `<div class="text-muted small text-center">${__("Guest in room")}</div>`;
                else if (r.status === "Out of Order") action = `<div class="text-muted small text-center">${__("Under maintenance")}</div>`;
                return `<div class="fd-hk-card fd-st-${st.cls}">
                    <div class="fd-rc-top"><span class="fd-rc-num">${FD.esc(r.room_number || r.name)}</span>${FD.room_pill(r.status)}</div>
                    <div class="fd-rc-type">${FD.esc(r.room_type)}${r.floor ? ` · ${__("Floor")} ${FD.esc(r.floor)}` : ""}</div>
                    <div class="fd-hk-actions">${action}<button class="btn btn-link btn-xs fd-hk-view" data-room="${FD.esc(r.name)}">${__("View Room")}</button></div>
                </div>`;
            }).join("")}</div>`);
        };
        draw();
        $tab.find(".fd-seg-btn").on("click", function () { f.status = $(this).data("st"); $tab.find(".fd-seg-btn").removeClass("active"); $(this).addClass("active"); draw(); });
        $tab.find(".fd-hk-floor").on("change", function () { f.floor = $(this).val(); draw(); });
        $tab.find(".fd-hk-text").on("input", frappe.utils.debounce(function () { f.text = $(this).val(); draw(); }, 200));
        $tab.on("click", ".fd-hk-act", function () {
            const room = $(this).data("room");
            FD.call("hospitality_core.api.console.set_housekeeping", { room_number: room, action: $(this).data("act") }, { btn: this })
                .then((r) => me.done(null, __("Room {0} is now {1}", [room, __(r.status)])));
        });
        $tab.on("click", ".fd-hk-view", function () {
            const room = s.rooms.find((r) => r.name === $(this).data("room"));
            if (room) me.show_room_dialog(room);
        });
    },

    // ---------------- MAINTENANCE ----------------
    render_maintenance($tab) {
        const me = this;
        const issues = this.state.maintenance || [];
        const ooo = (this.state.rooms || []).filter((r) => r.status === "Out of Order");
        $tab.html(`
            <div class="fd-toolbar">
                <div class="text-muted">${__("{0} open issues · {1} rooms out of order", [issues.length, ooo.length])}</div>
                <div style="flex:1"></div>
                <button class="btn btn-danger btn-sm fd-mt-new">${FD.icon("wrench")} ${__("Report Issue")}</button>
            </div>
            <div class="fd-mt-list"></div>`);
        const $l = $tab.find(".fd-mt-list");
        if (!issues.length) $l.html(FD.empty(__("No open maintenance issues."), "check"));
        else $l.html(`<div class="fd-table-wrap"><table class="fd-table"><thead><tr>
                <th>${__("Room")}</th><th>${__("Issue")}</th><th>${__("Priority")}</th><th>${__("Status")}</th><th>${__("Reported")}</th><th></th></tr></thead>
            <tbody>${issues.map((i) => `<tr>
                <td data-label="${__("Room")}"><b>${FD.esc(i.hotel_room)}</b></td>
                <td data-label="${__("Issue")}">${fd_doc_link("Issue", i.name, i.subject)}</td>
                <td data-label="${__("Priority")}"><span class="indicator-pill ${i.priority === "High" || i.priority === "Urgent" ? "red" : "orange"}">${FD.esc(i.priority || "")}</span></td>
                <td data-label="${__("Status")}">${FD.esc(i.status)}</td>
                <td data-label="${__("Reported")}">${frappe.datetime.comment_when(i.creation)}</td>
                <td class="fd-row-actions"><button class="btn btn-success btn-xs fd-mt-resolve" data-issue="${FD.esc(i.name)}">${__("Resolve")}</button></td>
            </tr>`).join("")}</tbody></table></div>`);
        $tab.find(".fd-mt-new").on("click", () => me.dialog_report_issue());
        $tab.on("click", ".fd-mt-resolve", function () { me.dialog_resolve_issue($(this).data("issue")); });
    },

    // ---------------- AVAILABILITY ----------------
    render_availability($tab) {
        const me = this;
        this.av = this.av || { from: this.current_date, to: frappe.datetime.add_days(this.current_date, 1), room_type: "" };
        const a = this.av;
        $tab.html(`
            <div class="fd-toolbar fd-av-form">
                <label>${__("Check-in")}<input type="date" class="form-control input-sm fd-av-from" value="${a.from}"></label>
                <label>${__("Check-out")}<input type="date" class="form-control input-sm fd-av-to" value="${a.to}"></label>
                <label>${__("Room Type")}<select class="form-control input-sm fd-av-type"><option value="">${__("All")}</option>
                    ${(this.state.room_types || []).map((t) => `<option ${t === a.room_type ? "selected" : ""}>${FD.esc(t)}</option>`).join("")}</select></label>
                <button class="btn btn-primary btn-sm fd-av-go">${FD.icon("search")} ${__("Check")}</button>
            </div>
            <div class="fd-av-result"></div>`);
        const run = () => {
            a.from = $tab.find(".fd-av-from").val();
            a.to = $tab.find(".fd-av-to").val();
            a.room_type = $tab.find(".fd-av-type").val();
            const $r = $tab.find(".fd-av-result");
            if (!a.from || !a.to || a.to <= a.from) { $r.html(FD.empty(__("Check-out must be after check-in."), "circle-alert")); return; }
            $r.html(FD.skeleton(4));
            const types = a.room_type ? [a.room_type] : (me.state.room_types || []);
            Promise.all(types.map((t) => FD.call("hospitality_core.api.console.get_available_rooms",
                { room_type: t, check_in_date: a.from, check_out_date: a.to }).then((rooms) => ({ type: t, rooms: rooms || [] }))))
                .then((groups) => {
                    if (!groups.length) { $r.html(FD.empty(__("No room types configured."), "bed-double")); return; }
                    const nights = frappe.datetime.get_diff(a.to, a.from);
                    $r.html(groups.map((g) => `
                        <div class="fd-av-group">
                            <div class="fd-av-head">
                                <div><b>${FD.esc(g.type)}</b> <span class="text-muted">· ${__("{0} available", [g.rooms.length])}</span></div>
                                <div>${g.rooms.length ? `${FD.money(g.rooms[0].rate)} / ${__("night")} · ${__("{0} nights", [nights])} = <b>${FD.money(g.rooms[0].rate * nights)}</b>` : ""}</div>
                            </div>
                            <div class="fd-av-rooms">${g.rooms.length ? g.rooms.map((r) => `
                                <button class="fd-av-room" data-room="${FD.esc(r.name)}" data-type="${FD.esc(g.type)}">${FD.esc(r.room_number || r.name)}
                                    <small>${r.floor ? __("Floor") + " " + FD.esc(r.floor) : ""}</small></button>`).join("")
                                : `<span class="text-muted">${__("Sold out for these dates")}</span>`}</div>
                        </div>`).join(""));
                    $r.find(".fd-av-room").on("click", function () {
                        me.dialog_new_reservation($(this).data("room"), $(this).data("type"), a.from, a.to);
                    });
                });
        };
        $tab.find(".fd-av-go").on("click", run);
        run();
    },
});
