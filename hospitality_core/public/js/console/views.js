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




    // ---------------- OTA BOOKINGS (POLISHED ENTERPRISE UI/UX) ----------------
    render_ota_bookings($tab) {
        const me = this;
        this.ota_filters = this.ota_filters || { status: "", text: "" };
        const f = this.ota_filters;

        const formatMoney = (amount, curr) => {
            curr = (curr || "GBP").trim().toUpperCase();
            const symbols = { "GBP": "£", "USD": "$", "EUR": "€", "INR": "₹", "AED": "AED" };
            const sym = symbols[curr] || curr + " ";
            const val = parseFloat(amount || 0);
            return `${sym} ${val.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        };

        const getChannelBadge = (ch) => {
            const channel = (ch || "OTA").trim();
            const lower = channel.toLowerCase();
            let bg = "#0284c7";
            let color = "#fff";
            let label = channel;

            if (lower.includes("booking")) {
                bg = "#003580"; label = "BOOKING.COM";
            } else if (lower.includes("expedia")) {
                bg = "#00355f"; color = "#ffd200"; label = "EXPEDIA";
            } else if (lower.includes("airbnb")) {
                bg = "#ff5a5f"; label = "AIRBNB";
            } else if (lower.includes("agoda")) {
                bg = "#5856d6"; label = "AGODA";
            } else if (lower.includes("makemytrip") || lower.includes("mmt")) {
                bg = "#eb2227"; label = "MAKEMYTRIP";
            }
            return `<span class="fd-channel-tag" style="background:${bg};color:${color}">${FD.esc(label)}</span>`;
        };

        $tab.html(`
            <div class="fd-ota-wrap">
                <!-- 4 Top KPI Cards -->
                <div class="fd-ota-kpis">
                    <div class="fd-ota-kpi-card pending">
                        <div class="fd-ota-kpi-icon">${FD.icon("alert-circle")}</div>
                        <div class="fd-ota-kpi-body">
                            <div class="fd-ota-kpi-val fd-kpi-new-count">0</div>
                            <div class="fd-ota-kpi-lbl">${__("Pending Acceptance")}</div>
                        </div>
                    </div>
                    <div class="fd-ota-kpi-card accepted">
                        <div class="fd-ota-kpi-icon">${FD.icon("check-circle-2")}</div>
                        <div class="fd-ota-kpi-body">
                            <div class="fd-ota-kpi-val fd-kpi-acc-count">0</div>
                            <div class="fd-ota-kpi-lbl">${__("Accepted & Reserved")}</div>
                        </div>
                    </div>
                    <div class="fd-ota-kpi-card revenue">
                        <div class="fd-ota-kpi-icon">${FD.icon("credit-card")}</div>
                        <div class="fd-ota-kpi-body">
                            <div class="fd-ota-kpi-val fd-kpi-revenue">0.00</div>
                            <div class="fd-ota-kpi-lbl">${__("Total OTA Revenue")}</div>
                        </div>
                    </div>
                    <div class="fd-ota-kpi-card total">
                        <div class="fd-ota-kpi-icon">${FD.icon("globe")}</div>
                        <div class="fd-ota-kpi-body">
                            <div class="fd-ota-kpi-val fd-kpi-total-count">0</div>
                            <div class="fd-ota-kpi-lbl">${__("Total Bookings")}</div>
                        </div>
                    </div>
                </div>

                <!-- Modern Toolbar -->
                <div class="fd-ota-toolbar">
                    <div class="fd-seg fd-ota-status-seg">
                        <button class="fd-seg-btn ${!f.status ? "active" : ""}" data-st="">${__("All")}</button>
                        <button class="fd-seg-btn ${f.status === "New" ? "active" : ""}" data-st="New">
                            <span class="fd-dot orange"></span>${__("Pending Acceptance")}
                        </button>
                        <button class="fd-seg-btn ${f.status === "Accepted" ? "active" : ""}" data-st="Accepted">
                            <span class="fd-dot green"></span>${__("Accepted")}
                        </button>
                        <button class="fd-seg-btn ${f.status === "Cancelled" ? "active" : ""}" data-st="Cancelled">
                            ${__("Cancelled")}
                        </button>
                    </div>

                    <div class="fd-ota-search-box">
                        ${FD.icon("search")}
                        <input class="form-control input-sm fd-ota-text" placeholder="${__("Search guest, booking ref, channel, room...")}" value="${FD.esc(f.text)}">
                    </div>

                    <div class="fd-ota-tools-right">
                        <span class="fd-ota-badge-sync">${FD.icon("activity")} ${__("Auto-sync: every 15m")}</span>
                        <button class="btn btn-default btn-sm fd-ota-fetch">
                            ${FD.icon("refresh-cw")} <span>${__("Fetch Now")}</span>
                        </button>
                        <button class="btn btn-default btn-sm fd-ota-push-inv" title="${__("Push Live Room Availability to Channex OTAs")}">
                            ${FD.icon("upload-cloud")} <span>${__("Push to OTA")}</span>
                        </button>
                        <button class="btn btn-default btn-sm fd-ota-settings" title="${__("OTA Settings")}">
                            ${FD.icon("settings")}
                        </button>
                    </div>
                </div>

                <!-- Table Content -->
                <div class="fd-ota-table-area">${FD.skeleton(4)}</div>
            </div>
        `);

        const load = () => {
            FD.call("hospitality_core.api.console.get_ota_bookings", { status: f.status, text: f.text }).then((rows) => {
                rows = rows || [];
                const $area = $tab.find(".fd-ota-table-area");

                const newCount = rows.filter(r => r.status === "New" && !r.hotel_reservation).length;
                const accCount = rows.filter(r => r.hotel_reservation || r.status === "Accepted").length;
                let revTotal = 0;
                let curr = "GBP";
                rows.forEach(r => {
                    revTotal += (r.total_amount || 0);
                    if (r.currency) curr = r.currency;
                });

                $tab.find(".fd-kpi-new-count").text(newCount);
                $tab.find(".fd-kpi-acc-count").text(accCount);
                $tab.find(".fd-kpi-total-count").text(rows.length);
                $tab.find(".fd-kpi-revenue").text(formatMoney(revTotal, curr));

                if (!rows.length) {
                    $area.html(FD.empty(__("No OTA bookings match the selected filters."), "globe"));
                    return;
                }

                $area.html(`
                    <div class="fd-table-wrap">
                        <table class="fd-table fd-ota-table">
                            <thead>
                                <tr>
                                    <th>${__("OTA Reference & Channel")}</th>
                                    <th>${__("Guest Information")}</th>
                                    <th>${__("Stay & Occupancy")}</th>
                                    <th>${__("Room Type & Rate Plan")}</th>
                                    <th class="text-right">${__("Total Amount")}</th>
                                    <th>${__("Status")}</th>
                                    <th class="text-right" style="min-width:180px">${__("Action")}</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${rows.map((r) => {
                    const isAccepted = !!r.hotel_reservation || r.status === "Accepted";
                    let statusHtml = "";
                    if (isAccepted) {
                        if (r.res_status === "Checked In") {
                            statusHtml = `<span class="fd-pill-status in-house"><span class="fd-dot green"></span>${__("In-House")}</span>`;
                        } else {
                            statusHtml = `<span class="fd-pill-status accepted"><span class="fd-dot green"></span>${__("Accepted")}</span>`;
                        }
                    } else if (r.status === "Cancelled") {
                        statusHtml = `<span class="fd-pill-status cancelled">${__("Cancelled")}</span>`;
                    } else {
                        statusHtml = `<span class="fd-pill-status pending"><span class="fd-dot orange"></span>${__("Needs Acceptance")}</span>`;
                    }

                    // Guest Initials
                    const initials = (r.guest_name || "G").split(" ").map(w => w[0]).slice(0, 2).join("").toUpperCase();

                    return `
                                        <tr data-name="${FD.esc(r.name)}" data-res="${FD.esc(r.hotel_reservation || "")}" class="fd-ota-row">
                                            <td>
                                                <div class="fd-ota-ref-col">
                                                    <span class="fd-ota-ref-id">${FD.esc(r.ota_booking_id || r.name)}</span>
                                                    ${getChannelBadge(r.channel_name)}
                                                </div>
                                            </td>
                                            <td>
                                                <div class="fd-ota-guest-cell">
                                                    <div class="fd-guest-avatar">${FD.esc(initials)}</div>
                                                    <div>
                                                        <div class="fd-guest-name">${FD.esc(r.guest_name || __("OTA Guest"))}</div>
                                                        <div class="fd-guest-contact text-muted">${FD.esc(r.guest_phone || r.guest_email || "—")}</div>
                                                    </div>
                                                </div>
                                            </td>
                                            <td>
                                                <div class="fd-stay-cell">
                                                    <div class="fd-stay-dates">${FD.date(r.check_in_date)} &rarr; ${FD.date(r.check_out_date)}</div>
                                                    <div class="fd-stay-tags">
                                                        <span class="fd-tag-nights">${r.nights || 1} ${__("night(s)")}</span>
                                                        <span class="text-muted small">${r.adults || 1} ${__("Adult(s)")}</span>
                                                    </div>
                                                </div>
                                            </td>
                                            <td>
                                                ${(() => {
                                                    const isUuid = (s) => typeof s === "string" && s.trim().length === 36 && s.indexOf("-") !== -1;
                                                    const rt = (r.room_type_name && !isUuid(r.room_type_name)) ? r.room_type_name : "Demo Double";
                                                    const rp = (r.rate_plan_name && !isUuid(r.rate_plan_name)) ? r.rate_plan_name : "Standard Rate";
                                                    return `
                                                        <div class="fd-room-cell">
                                                            <div class="fd-room-type-title">${FD.esc(rt)}</div>
                                                            <div class="fd-rate-plan-tag">${FD.esc(rp)}</div>
                                                        </div>
                                                    `;
                                                })()}
                                            </td>
                                            <td class="text-right">
                                                <div class="fd-amount-cell">
                                                    <div class="fd-amount-val">${formatMoney(r.total_amount, r.currency)}</div>
                                                    <div class="text-muted small">${FD.esc(r.payment_status || "OTA Collect")}</div>
                                                </div>
                                            </td>
                                            <td>${statusHtml}</td>
                                            <td class="text-right fd-actions-cell">
                                                ${isAccepted ? `
                                                    ${r.res_status === "Reserved" ? `
                                                        <button class="btn btn-primary btn-xs fd-btn-checkin-ota" data-res="${FD.esc(r.hotel_reservation)}" title="${__("Check In Guest")}">
                                                            ${FD.icon("log-in")} <span>${__("Check In")}</span>
                                                        </button>
                                                    ` : ""}
                                                    <button class="btn btn-default btn-xs fd-btn-view-res" data-res="${FD.esc(r.hotel_reservation)}" title="${__("Open Hotel Reservation")}">
                                                        ${FD.icon("calendar")} <span>${FD.esc(r.hotel_reservation)}</span>
                                                    </button>
                                                ` : (r.status !== "Cancelled" ? `
                                                    <button class="btn btn-success btn-xs fd-btn-accept" data-name="${FD.esc(r.name)}" data-guest="${FD.esc(r.guest_name)}" data-rt="${FD.esc(r.room_type_name || "")}" data-dates="${FD.date(r.check_in_date)} - ${FD.date(r.check_out_date)}">
                                                        ${FD.icon("check")} <span>${__("Accept Booking")}</span>
                                                    </button>
                                                ` : "")}
                                                <button class="btn btn-default btn-xs fd-btn-wa" data-name="${FD.esc(r.name)}" data-res="${FD.esc(r.hotel_reservation || '')}" title="${__("WhatsApp Guest & Pre-Checkin Link")}">
                                                    <span style="color:#16a34a;font-weight:800;">WA</span>
                                                </button>
                                                <button class="btn btn-default btn-xs fd-btn-raw" data-name="${FD.esc(r.name)}" title="${__("View Booking Voucher & Details")}" onclick="if(window.fd_dialog_ota_details){ window.fd_dialog_ota_details('${FD.esc(r.name)}'); } else if(window.cur_fd_console && window.cur_fd_console.dialog_ota_details){ window.cur_fd_console.dialog_ota_details('${FD.esc(r.name)}'); } else { fd_open_doc_popup('OTA Reservation', '${FD.esc(r.name)}'); } event.stopPropagation();">
                                                    ${FD.icon("eye")}
                                                </button>
                                            </td>
                                        </tr>
                                    `;
                }).join("")}
                            </tbody>
                        </table>
                    </div>
                `);
            });
        };

        // Filter events
        $tab.find(".fd-ota-status-seg .fd-seg-btn").on("click", function () {
            f.status = $(this).data("st");
            $tab.find(".fd-ota-status-seg .fd-seg-btn").removeClass("active");
            $(this).addClass("active");
            load();
        });

        $tab.find(".fd-ota-text").on("input", frappe.utils.debounce(function () {
            f.text = $(this).val();
            load();
        }, 250));

        // Push to OTA button (2-Way Instant Sync)
        $tab.find(".fd-ota-push-inv").on("click", (e) => {
            frappe.confirm(
                __("<b>Push Live Inventory to Channex OTAs?</b><br><br>This will calculate remaining free rooms for all room types across the next 30 days and update Channex/Booking.com/Airbnb in real-time to prevent overbooking."),
                () => {
                    FD.call("hospitality_core.api.ota.sync_push_inventory", {}, {
                        btn: e.currentTarget,
                        freeze: true,
                        freeze_message: __("Pushing live inventory to Channex...")
                    }).then((r) => {
                        frappe.show_alert({
                            message: r.message || __("Inventory pushed to OTAs!"),
                            indicator: "green"
                        });
                    }).catch((err) => {
                        frappe.msgprint({
                            title: __("Push Failed"),
                            message: err.message || String(err),
                            indicator: "red"
                        });
                    });
                }
            );
        });

        // WhatsApp Guest Action
        $tab.on("click", ".fd-btn-wa", function (e) {
            e.stopPropagation();
            const otaName = $(this).data("name");
            const resName = $(this).data("res");
            me.dialog_whatsapp(resName, otaName);
        });

        // Fetch Now button
        $tab.find(".fd-ota-fetch").on("click", (e) => {
            FD.call("hospitality_core.api.ota.pull_booking_revisions", {}, {
                btn: e.currentTarget,
                freeze: true,
                freeze_message: __("Syncing rooms & bookings with Channex...")
            }).then((r) => {
                if (r && r.processed > 0) {
                    frappe.show_alert({
                        message: __("Success! Fetched {0} booking(s) from Channex.", [r.processed]),
                        indicator: "green"
                    });
                } else {
                    frappe.msgprint({
                        title: __("Sync Completed"),
                        indicator: "blue",
                        message: __("Sync completed, but <b>0 new bookings</b> were found.<br><br><b>Connected Property:</b> <code>{0}</code><br><br>💡 <b>Tip:</b> If your booking was created under a new property in Channex, open <b>OTA Settings</b>, click <b>'Select Property'</b>, and choose your new property.", [r.property_id || __("Not set")])
                    });
                }
                load();
                me.load_data(true);
            }).catch((err) => {
                frappe.msgprint({
                    title: __("Sync Error"),
                    message: err.message || String(err),
                    indicator: "red"
                });
            });
        });

        // Settings button
        $tab.find(".fd-ota-settings").on("click", () => {
            frappe.set_route("Form", "OTA Settings");
        });

        // Accept Booking Action
        $tab.on("click", ".fd-btn-accept", function (e) {
            e.stopPropagation();
            const otaName = $(this).data("name");
            const guest = $(this).data("guest") || __("Guest");
            const rt = $(this).data("rt") || "";
            const dates = $(this).data("dates") || "";

            frappe.confirm(
                __("<b>Accept OTA Booking for {0}?</b><br><br><b>Stay:</b> {1}<br><b>Room Type:</b> {2}<br><br>This will create a confirmed <b>Hotel Reservation</b> (status: <i>Reserved</i>). Upon guest arrival, front desk staff can check them in and allot their physical room with 1 click.", [guest, dates, rt]),
                () => {
                    FD.call("hospitality_core.api.console.accept_ota_booking", {
                        ota_reservation_name: otaName
                    }, { freeze: true, freeze_message: __("Creating Hotel Reservation...") })
                        .then((r) => {
                            frappe.show_alert({
                                message: __("Accepted! Created Hotel Reservation {0}", [r.reservation]),
                                indicator: "green"
                            });
                            load();
                            me.load_data(true);
                        })
                        .catch((err) => {
                            let msg = err && err.message ? err.message : "";
                            if (!msg && err && err._server_messages) {
                                try {
                                    const parsed = JSON.parse(err._server_messages);
                                    msg = JSON.parse(parsed[0]).message || parsed[0];
                                } catch (e) { }
                            }
                            frappe.msgprint({
                                title: __("Accept Failed"),
                                message: msg || (typeof err === "string" ? err : JSON.stringify(err)),
                                indicator: "red"
                            });
                        });
                }
            );
        });

        // Direct Check-in Action
        $tab.on("click", ".fd-btn-checkin-ota", function (e) {
            e.stopPropagation();
            const resName = $(this).data("res");
            if (resName) {
                me.dialog_checkin(resName);
            }
        });

        // View Reservation Dialog
        $tab.on("click", ".fd-btn-view-res", function (e) {
            e.stopPropagation();
            const resName = $(this).data("res");
            if (resName) {
                me.dialog_reservation(resName);
            }
        });

        // Direct click on Eye Button
        $tab.on("click", ".fd-btn-raw", function (e) {
            e.preventDefault();
            e.stopPropagation();
            const $btn = $(this);
            const name = $btn.attr("data-name") || $btn.data("name") || $btn.closest("tr").attr("data-name") || $btn.closest("tr").data("name");
            if (name) {
                if (window.fd_dialog_ota_details) {
                    window.fd_dialog_ota_details(name);
                } else if (me.dialog_ota_details) {
                    me.dialog_ota_details(name);
                } else {
                    fd_open_doc_popup("OTA Reservation", name);
                }
            }
        });

        // Click on entire OTA table row to view details
        $tab.on("click", ".fd-ota-row", function (e) {
            if ($(e.target).closest(".fd-btn-accept, .fd-btn-view-res, .fd-btn-checkin-ota, .fd-btn-wa, .fd-btn-raw, a, button").length) return;
            const name = $(this).attr("data-name") || $(this).data("name");
            if (name) {
                if (window.fd_dialog_ota_details) {
                    window.fd_dialog_ota_details(name);
                } else if (me.dialog_ota_details) {
                    me.dialog_ota_details(name);
                } else {
                    fd_open_doc_popup("OTA Reservation", name);
                }
            }
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
