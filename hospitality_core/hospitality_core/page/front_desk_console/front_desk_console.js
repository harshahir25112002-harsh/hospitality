/**
 * Sky Hotel Management System - Front Desk Console v3
 * Single-screen console: every action opens a popup, nothing navigates away.
 *
 * Modules (concatenated server-side by Frappe's include directive for page scripts):
 *   public/js/console/core.js        helpers, popup mode, doc / print popups
 *   public/js/console/views.js       tabs: room board, lists, reservations, tape chart, housekeeping, ...
 *   public/js/console/dialogs.js     reservation / payment / billing / room operations
 *   public/js/console/pos_overlay.js standard ERPNext POS in an overlay
 *   public/js/console/razorpay.js    Razorpay online payment requests (QR / link / this screen)
 */

{% include "hospitality_core/public/js/console/core.js" %}

frappe.pages["front-desk-console"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Front Desk Console"),
        single_column: true,
    });
    try {
        window.cur_fd_console = new FrontDeskConsole(wrapper, page);
    } catch (e) {
        console.error(e);
        $(page.main).html(`<div class="text-center p-5 text-danger">${__("Front Desk Console failed to start")}: ${frappe.utils.escape_html(e.message)}</div>`);
    }
};

frappe.pages["front-desk-console"].on_page_show = function () {
    if (window.cur_fd_console && window.cur_fd_console.state) window.cur_fd_console.load_data(true);
};

class FrontDeskConsole {
    constructor(wrapper, page) {
        this.wrapper = $(wrapper);
        this.page = page;
        this.current_date = frappe.datetime.get_today();
        this.active_tab = "rooms";
        this.state = null;
        this.filters = { floor: "", room_type: "", status: "", text: "" };
        this.res_filters = { status: "Upcoming", text: "" };

        fd_install_popup_mode();
        this.init_dom();
        this.init_keyboard_shortcuts();
        this.init_realtime();
        this.load_data();
    }

    init_dom() {
        const I = FD.icon;
        this.$container = $(`
            <div class="fd-console">
                <div class="fd-header">
                    <div class="fd-brand">
                        <div class="fd-brand-icon">${I("building-2", "md")}</div>
                        <div>
                            <div class="fd-brand-title">${__("Sky Hotel")}</div>
                            <div class="fd-brand-sub">${__("Front Desk")}</div>
                        </div>
                    </div>
                    <div class="fd-date-nav">
                        <button class="btn btn-default btn-sm fd-icon-btn fd-prev-day" title="${__("Previous day")}">${I("chevron-left")}</button>
                        <div class="fd-date-display">${I("calendar")}<span class="fd-display-date"></span></div>
                        <button class="btn btn-default btn-sm fd-icon-btn fd-next-day" title="${__("Next day")}">${I("chevron-right")}</button>
                        <button class="btn btn-default btn-sm fd-today-btn">${__("Today")}</button>
                    </div>
                    <div class="fd-search-box">
                        <span class="fd-search-icon">${I("search")}</span>
                        <input type="text" class="form-control fd-global-search" placeholder="${__("Search guest, room, reservation…  ( / )")}">
                        <div class="fd-search-results"></div>
                    </div>
                    <div class="fd-actions">
                        <button class="btn btn-primary btn-sm fd-btn-new-res">${I("calendar-plus")}<span>${__("Reservation")}</span></button>
                        <button class="btn btn-success btn-sm fd-btn-walkin">${I("log-in")}<span>${__("Walk-in")}</span></button>
                        <button class="btn btn-default btn-sm fd-btn-rest-pos">${I("utensils")}<span>${__("Restaurant POS")}</span></button>
                        <button class="btn btn-default btn-sm fd-btn-room-pos">${I("bell")}<span>${__("Room Service")}</span></button>
                        <button class="btn btn-default btn-sm fd-icon-btn fd-btn-refresh" title="${__("Refresh (R)")}">${I("refresh-cw")}</button>
                    </div>
                </div>

                <div class="fd-warnings"></div>
                <div class="fd-kpis"></div>

                <div class="fd-tabs" role="tablist">
                    ${[
                ["rooms", "layout-grid", __("Room Board")],
                ["arrivals", "log-in", __("Arrivals")],
                ["in_house", "users", __("In-House")],
                ["departures", "log-out", __("Departures")],
                ["reservations", "list", __("Reservations")],
                ["ota_bookings", "globe", __("OTA Bookings")],
                ["tape_chart", "calendar-range", __("Tape Chart")],
                ["housekeeping", "sparkles", __("Housekeeping")],
                ["maintenance", "wrench", __("Maintenance")],
                ["availability", "bed-double", __("Availability")], 
            ].map(([k, ic, l]) => `<button class="fd-tab" data-tab="${k}">${I(ic)}<span>${l}</span><span class="fd-tab-count" data-count="${k}"></span></button>`).join("")}
                </div>

                <div class="fd-tab-content">${FD.skeleton(12)}</div>
            </div>
        `).appendTo(this.page.main && this.page.main.length ? this.page.main : this.wrapper.find(".layout-main-section"));

        this.bind_events();
    }

    bind_events() {
        const me = this;
        const $c = this.$container;
        $c.find(".fd-prev-day").on("click", () => me.change_date(-1));
        $c.find(".fd-next-day").on("click", () => me.change_date(1));
        $c.find(".fd-today-btn").on("click", () => { me.current_date = frappe.datetime.get_today(); me.load_data(); });
        $c.find(".fd-btn-refresh").on("click", () => me.load_data());
        $c.find(".fd-btn-new-res").on("click", () => me.dialog_new_reservation());
        $c.find(".fd-btn-walkin").on("click", () => me.dialog_walkin());
        $c.find(".fd-btn-rest-pos").on("click", () => me.open_pos_overlay("restaurant"));
        $c.find(".fd-btn-room-pos").on("click", () => me.dialog_pick_room_service_guest());
        $c.on("click", ".fd-tab", function () { me.switch_tab($(this).data("tab")); });
        $c.on("click", ".fd-kpi", function () {
            const tab = $(this).data("tab");
            const st = $(this).data("status");
            if (tab === "rooms") me.filters.status = st || "";
            me.switch_tab(tab);
        });
        this.bind_search();
    }

    bind_search() {
        const me = this;
        const $input = this.$container.find(".fd-global-search");
        const $results = this.$container.find(".fd-search-results");

        $input.on("input", frappe.utils.debounce(function () {
            const val = $(this).val();
            if (!val || val.length < 2) { $results.hide().empty(); return; }
            FD.call("hospitality_core.api.console.search", { text: val }).then((list) => {
                $results.empty();
                if (!list || !list.length) {
                    $results.html(`<div class="fd-search-empty">${__("No matches found.")}</div>`).show();
                    return;
                }
                const icons = { Room: "bed-double", Reservation: "calendar", Guest: "user" };
                list.forEach((item) => {
                    $results.append(`
                        <div class="fd-search-item" data-type="${FD.esc(item.type)}" data-val="${FD.esc(item.value)}">
                            <span class="fd-search-type">${FD.icon(icons[item.type] || "search")}</span>
                            <div><div>${FD.esc(item.label)}</div><small class="text-muted">${FD.esc(item.details)}</small></div>
                        </div>`);
                });
                $results.show();
            }).catch(() => { });
        }, 300));

        $results.on("click", ".fd-search-item", function () {
            const type = $(this).attr("data-type");
            const val = $(this).attr("data-val");
            $results.hide();
            $input.val("");
            if (type === "Room") {
                const room = (me.state.rooms || []).find((r) => r.name === val);
                if (room) me.show_room_dialog(room);
            } else if (type === "Reservation") {
                me.dialog_reservation(val);
            } else if (type === "Guest") {
                me.dialog_guest(val);
            }
        });

        $(document).on("click.fdsearch", (e) => {
            if (!$(e.target).closest(".fd-search-box").length) $results.hide();
        });
    }

    init_keyboard_shortcuts() {
        const me = this;
        $(document).on("keydown.fdconsole", function (e) {
            if (!fd_on_console() || window.cur_dialog && window.cur_dialog.display) return;
            if ($(e.target).is("input, textarea, select, [contenteditable]")) return;
            if (e.ctrlKey || e.metaKey || e.altKey) return;
            const k = e.key.toLowerCase();
            if (k === "n") { e.preventDefault(); me.dialog_new_reservation(); }
            else if (k === "w") { e.preventDefault(); me.dialog_walkin(); }
            else if (k === "r") { e.preventDefault(); me.load_data(); }
            else if (e.key === "/") { e.preventDefault(); me.$container.find(".fd-global-search").focus(); }
        });
    }

    init_realtime() {
        frappe.realtime.on("hotel_console_update", frappe.utils.debounce(() => {
            if (fd_on_console()) this.load_data(true);
        }, 500));
        // POS overlay notifies us after Charge to Room
        window.addEventListener("message", (e) => {
            if (e.origin === window.location.origin && e.data && e.data.type === "hotel_room_charge") this.load_data(true);
        });
    }

    change_date(delta) {
        this.current_date = frappe.datetime.add_days(this.current_date, delta);
        this.load_data();
    }

    load_data(silent = false) {
        const me = this;
        const $ref = this.$container.find(".fd-btn-refresh");
        $ref.addClass("fd-spin");
        if (!silent && !this.state) this.$container.find(".fd-tab-content").html(FD.skeleton(12));
        return FD.call("hospitality_core.api.console.get_console_data", { target_date: me.current_date })
            .then((data) => {
                me.state = data;
                try {
                    me.render();
                } catch (e) {
                    console.error(e);
                    me.show_error(e.message || String(e));
                }
            })
            .catch(() => {
                if (!me.state) me.show_error(__("Could not load console data. Check Hotel Settings and your permissions."));
            })
            .finally(() => $ref.removeClass("fd-spin"));
    }

    show_error(msg) {
        const $c = this.$container.find(".fd-tab-content");
        $c.html(`<div class="fd-empty fd-error">${FD.icon("circle-alert", "lg")}
            <div>${FD.esc(msg)}</div>
            <button class="btn btn-primary btn-sm fd-retry">${__("Retry")}</button></div>`);
        $c.find(".fd-retry").on("click", () => { $c.html(FD.skeleton(12)); this.load_data(); });
    }

    render() {
        const s = this.state;
        const today = frappe.datetime.get_today();
        this.$container.find(".fd-display-date").text(
            frappe.datetime.str_to_user(this.current_date) + (this.current_date === today ? ` · ${__("Today")}` : "")
        );
        this.$container.find(".fd-brand-title").text(s.hotel_name || __("Sky Hotel"));
        this.render_warnings();
        this.render_kpis();
        this.render_tab_counts();
        this.render_tab_content();
    }

    render_warnings() {
        const w = this.state.setup_warnings || [];
        const $w = this.$container.find(".fd-warnings");
        if (!w.length) { $w.empty().hide(); return; }
        const no_rooms = !this.state.kpis.total_rooms;
        $w.html(`
            <div class="fd-warning">
                ${FD.icon("circle-alert")}
                <div class="fd-warning-text">${w.map((x) => `<div>${FD.esc(x)}</div>`).join("")}</div>
                <div class="fd-warning-actions">
                    ${no_rooms && this.state.can_setup ? `<button class="btn btn-xs btn-primary fd-sample-rooms">${__("Create sample rooms")}</button>` : ""}
                    <button class="btn btn-xs btn-default fd-open-settings">${__("Hotel Settings")}</button>
                </div>
            </div>`).show();
        $w.find(".fd-open-settings").on("click", () => this.dialog_hotel_settings());
        $w.find(".fd-sample-rooms").on("click", (e) => {
            frappe.confirm(__("Create 2 room types (Standard, Deluxe) and 6 rooms (101-103, 201-203)?"), () => {
                FD.call("hospitality_core.api.console.create_sample_rooms", {}, { btn: e.currentTarget, freeze: true })
                    .then((r) => { frappe.show_alert({ message: __("{0} rooms created", [r.created.length]), indicator: "green" }); this.load_data(); });
            });
        });
    }

    render_kpis() {
        const k = this.state.kpis;
        const cards = [
            ["rooms", "", "building-2", k.total_rooms, __("Total Rooms"), "neutral"],
            ["arrivals", "", "log-in", k.arrivals, __("Arrivals"), "blue"],
            ["departures", "", "log-out", k.departures, __("Departures"), "orange"],
            ["in_house", "", "users", k.in_house, __("In-House"), "purple"],
            ["rooms", "Available", "check", k.available, __("Available"), "green"],
            ["rooms", "Occupied", "bed-double", k.occupied ?? 0, __("Occupied"), "dark"],
            ["housekeeping", "", "sparkles", k.dirty, __("Dirty"), "yellow"],
            ["maintenance", "", "wrench", k.ooo, __("Out of Order"), "red"],
            ["rooms", "", "percent", `${k.occupancy_pct}%`, __("Occupancy"), "teal"],
        ];
        this.$container.find(".fd-kpis").html(cards.map(([tab, st, ic, v, l, c]) => `
            <button class="fd-kpi fd-kpi-${c}" data-tab="${tab}" data-status="${st}">
                <span class="fd-kpi-icon">${FD.icon(ic)}</span>
                <span class="fd-kpi-body"><span class="fd-kpi-num">${FD.esc(v)}</span><span class="fd-kpi-label">${l}</span></span>
            </button>`).join(""));
    }

    render_tab_counts() {
        const s = this.state;
        const counts = {
            arrivals: s.arrivals.length, in_house: s.in_house.length, departures: s.departures.length,
            ota_bookings: s.ota_bookings_count,
            housekeeping: s.dirty.length, maintenance: s.maintenance.length,
        };
        this.$container.find(".fd-tab-count").each(function () {
            const n = counts[$(this).data("count")];
            $(this).text(n ? n : "").toggle(!!n);
        });
    }

    switch_tab(tab) {
        this.active_tab = tab;
        this.render_tab_content();
    }

    render_tab_content() {
        this.$container.find(".fd-tab").removeClass("active").attr("aria-selected", "false");
        this.$container.find(`.fd-tab[data-tab="${this.active_tab}"]`).addClass("active").attr("aria-selected", "true");
        const $tab = this.$container.find(".fd-tab-content").empty().off();
        const renderers = {
            rooms: () => this.render_room_board($tab),
            arrivals: () => this.render_arrivals($tab),
            in_house: () => this.render_in_house($tab),
            departures: () => this.render_departures($tab),
            reservations: () => this.render_reservations($tab),
            ota_bookings: () => this.render_ota_bookings($tab),
            tape_chart: () => this.render_tape_chart($tab),
            housekeeping: () => this.render_housekeeping($tab),
            maintenance: () => this.render_maintenance($tab),
            availability: () => this.render_availability($tab),
        };
        (renderers[this.active_tab] || renderers.rooms)();
    }

    /** after an operation: close dialog, toast, refresh */
    done(d, msg, indicator = "green") {
        if (d) d.hide();
        if (msg) frappe.show_alert({ message: msg, indicator });
        return this.load_data(true);
    }
}

{% include "hospitality_core/public/js/console/views.js" %}
{% include "hospitality_core/public/js/checkin_dialog.js" %}
{% include "hospitality_core/public/js/console/dialogs.js" %}
{% include "hospitality_core/public/js/console/pos_overlay.js" %}
{% include "hospitality_core/public/js/console/razorpay.js" %}
