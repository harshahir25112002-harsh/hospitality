/**
 * Front Desk Console - standard ERPNext Point of Sale in an overlay.
 * The POS itself is untouched; we only tell it (via localStorage, same origin) which
 * POS Profile to open and which in-house reservation to preselect.
 */
Object.assign(FrontDeskConsole.prototype, {

    dialog_pick_room_service_guest() {
        const me = this;
        const guests = this.state.in_house || [];
        if (!guests.length) {
            frappe.msgprint({ title: __("Room Service"), message: __("No guests are checked in. Room service can only be charged to in-house guests."), indicator: "orange" });
            return;
        }
        const d = FD.dialog({
            title: __("Room Service · Select Guest"),
            fields: [{ fieldtype: "HTML", fieldname: "list" }],
        });
        d.fields_dict.list.$wrapper.html(`<div class="fd-guest-pick">${guests.map((g) => `
            <button class="fd-guest-pick-item" data-res="${FD.esc(g.name)}" data-cust="${FD.esc(g.customer)}">
                <span class="fd-rc-num">${FD.esc(g.room)}</span>
                <span><b>${FD.esc(g.guest_name || g.customer)}</b><small class="text-muted d-block">${FD.esc(g.name)}</small></span>
            </button>`).join("")}</div>
            <button class="btn btn-default btn-sm mt-3 fd-guest-none">${__("Open without guest")}</button>`);
        d.fields_dict.list.$wrapper.on("click", ".fd-guest-pick-item", function () {
            d.hide();
            me.open_room_service_for($(this).data("res"), $(this).data("cust"));
        });
        d.fields_dict.list.$wrapper.on("click", ".fd-guest-none", () => { d.hide(); me.open_pos_overlay("room"); });
        d.show();
    },

    open_room_service_for(reservation, customer) {
        if (!customer) {
            const g = (this.state.in_house || []).find((x) => x.name === reservation);
            customer = g && g.customer;
        }
        this.open_pos_overlay("room", { reservation, customer });
    },

    open_pos_overlay(type = "room", ctx = {}) {
        const me = this;
        const s = this.state.settings || {};
        const profile = type === "restaurant" ? s.restaurant_pos_profile : s.room_pos_profile;
        const label = type === "restaurant" ? __("Restaurant POS") : __("Room Service POS");

        if (!profile) {
            frappe.msgprint({
                title: __("Setup required"), indicator: "orange",
                message: __("No {0} profile is configured in Hotel Settings.", [label]) +
                    `<br><br><button class="btn btn-sm btn-primary fd-open-settings-msg">${__("Open Hotel Settings")}</button>`,
            });
            $(".fd-open-settings-msg").on("click", () => { frappe.hide_msgprint(); me.dialog_hotel_settings(); });
            return;
        }

        FD.call("hospitality_core.api.console.ensure_pos_opening", { pos_profile: profile }, { freeze: true, freeze_message: __("Opening POS…") })
            .then(() => {
                try {
                    localStorage.setItem("hotel_pos_launch", JSON.stringify({
                        profile, customer: ctx.customer || null, reservation: ctx.reservation || null, ts: Date.now(),
                    }));
                } catch (e) { /* storage unavailable: POS still opens, guest picked manually */ }

                const url = "/desk/point-of-sale";
                $(".fd-pos-overlay").remove();
                const $o = $(`
                    <div class="fd-pos-overlay" role="dialog" aria-label="${FD.esc(label)}">
                        <div class="fd-pos-header">
                            <div class="fd-pos-title">${FD.icon(type === "restaurant" ? "utensils" : "bell")}
                                <b>${FD.esc(label)}</b><span class="fd-pos-badge">${FD.esc(profile)}</span>
                                ${ctx.reservation ? `<span class="fd-pos-badge">${__("Guest")}: ${FD.esc(ctx.reservation)}</span>` : ""}
                            </div>
                            <div>
                                <button class="btn btn-default btn-sm fd-pos-newtab">${__("Open in new tab")}</button>
                                <button class="btn btn-danger btn-sm fd-close-pos">${FD.icon("x")} ${__("Close")}</button>
                            </div>
                        </div>
                        <div class="fd-pos-loading">${__("Loading Point of Sale…")}</div>
                        <iframe class="fd-pos-iframe" src="${url}"></iframe>
                    </div>`).appendTo("body");
                $("body").addClass("fd-no-scroll");
                const close = () => { $o.remove(); $("body").removeClass("fd-no-scroll"); $(document).off("keydown.fdpos"); me.load_data(true); };
                $o.find(".fd-close-pos").on("click", close);
                $o.find(".fd-pos-newtab").on("click", () => { window.open(url, "_blank"); close(); });
                $(document).on("keydown.fdpos", (e) => { if (e.key === "Escape" && !$(e.target).is("input,textarea")) close(); });
                // If the iframe cannot load (e.g. X-Frame-Options), fall back to a new tab
                const iframe = $o.find("iframe")[0];
                const fallback = setTimeout(() => {
                    let ok = false;
                    try { ok = !!(iframe.contentWindow && iframe.contentWindow.frappe); } catch (e) { ok = false; }
                    if (!ok) $o.find(".fd-pos-loading").html(`${__("POS could not be embedded.")} <button class="btn btn-sm btn-primary fd-pos-fallback">${__("Open in new tab")}</button>`)
                        .find(".fd-pos-fallback").on("click", () => { window.open(url, "_blank"); close(); });
                }, 15000);
                iframe.addEventListener("load", () => {
                    try {
                        if (iframe.contentWindow && iframe.contentWindow.frappe) {
                            clearTimeout(fallback);
                            $o.find(".fd-pos-loading").hide();
                        }
                    } catch (e) { /* cross-origin: leave fallback timer */ }
                });
            });
    },
});
