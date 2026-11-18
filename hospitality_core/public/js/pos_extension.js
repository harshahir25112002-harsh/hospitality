/**
 * Sky Hotel Management System - POS Extension (loaded via hooks.page_js on "point-of-sale").
 *
 * Kept deliberately small and defensive; it never replaces standard POS behaviour:
 * 1. Launch context: the Front Desk Console stores {profile, customer, reservation} in
 *    localStorage("hotel_pos_launch"). The standard POS opens the user's most recent
 *    POS Opening Entry, so we only re-order the opening entries so the requested profile wins.
 * 2. Room Service profile: an "In-House Guest" picker (sets customer + hotel_reservation)
 *    and a "Charge to Room" button that saves the order as a draft flagged charge_to_room.
 * 3. Embedded mode styling when shown inside the console overlay (iframe).
 */
(function () {
    const LAUNCH_KEY = "hotel_pos_launch";
    const embedded = window.self !== window.top;

    function read_launch() {
        try {
            const v = JSON.parse(localStorage.getItem(LAUNCH_KEY) || "null");
            // launch context is only valid for 2 minutes
            if (v && Date.now() - (v.ts || 0) < 120000) return v;
        } catch (e) { /* storage unavailable */ }
        return null;
    }

    // ---------- 1. pick the requested POS profile ----------
    function patch_controller() {
        const C = window.erpnext && erpnext.PointOfSale && erpnext.PointOfSale.Controller;
        if (!C || C.prototype.__hotel_patched) return;
        C.prototype.__hotel_patched = true;
        const orig = C.prototype.fetch_opening_entry;
        C.prototype.fetch_opening_entry = function () {
            return orig.apply(this, arguments).then((r) => {
                const launch = read_launch();
                if (launch && launch.profile && r && Array.isArray(r.message)) {
                    const idx = r.message.findIndex((e) => e.pos_profile === launch.profile);
                    if (idx > 0) r.message.unshift(r.message.splice(idx, 1)[0]);
                }
                return r;
            });
        };
    }

    const page = frappe.pages["point-of-sale"];
    if (page && page.on_page_load && !page.__hotel_wrapped) {
        const orig_load = page.on_page_load;
        page.__hotel_wrapped = true;
        page.on_page_load = function (wrapper) {
            // load the POS bundle first so we can patch before the controller is constructed
            frappe.require("point-of-sale.bundle.js", () => {
                try { patch_controller(); } catch (e) { console.error("hotel pos patch", e); }
                orig_load(wrapper);
            });
        };
    }

    // ---------- 3. embedded styling ----------
    if (embedded) {
        document.body.classList.add("hotel-embedded");
    }
    if (!document.getElementById("hotel-pos-style")) {
        const style = document.createElement("style");
        style.id = "hotel-pos-style";
        style.innerHTML = `
            body.hotel-embedded .navbar, body.hotel-embedded .page-head,
            body.hotel-embedded .layout-side-section, body.hotel-embedded .body-sidebar-container,
            body.hotel-embedded .desk-sidebar { display: none !important; }
            body.hotel-embedded .main-section, body.hotel-embedded .page-container { padding: 0 !important; margin: 0 !important; }
            .hotel-charge-to-room-btn { background: #d97706 !important; color: #fff !important; font-weight: 600;
                margin-top: 8px; text-align: center; padding: 10px; border-radius: 8px; cursor: pointer; user-select: none; }
            .hotel-charge-to-room-btn.disabled { opacity: .6; pointer-events: none; }
            .hotel-in-house-picker { margin-bottom: 8px; }
            .hotel-in-house-picker select { width: 100%; }
            .hotel-guest-banner { background: var(--blue-50, #eff6ff); color: var(--blue-700, #1d4ed8);
                border-radius: 8px; padding: 6px 10px; font-size: 12px; margin-bottom: 8px; }
        `;
        document.head.appendChild(style);
    }

    // ---------- 2. Room Service tools ----------
    let room_profile = null;
    let timer = null;

    function pos() { return window.cur_pos; }

    function current_reservation() {
        const p = pos();
        return p && p.frm && p.frm.doc ? p.frm.doc.hotel_reservation : null;
    }

    function set_guest(customer, reservation) {
        const p = pos();
        if (!p || !p.frm) return;
        p.frm.doc.hotel_reservation = reservation || null;
        if (customer && p.frm.doc.customer !== customer) {
            // use the cart's own customer control so the standard POS onchange flow runs
            const field = p.cart && p.cart.customer_field;
            if (field && field.set_value) field.set_value(customer);
            else frappe.model.set_value(p.frm.doctype, p.frm.docname, "customer", customer);
        }
    }

    function tick() {
        const p = pos();
        if (!p || !p.pos_profile) return;
        const is_room = room_profile && p.pos_profile === room_profile;
        if (!is_room) {
            $(".hotel-in-house-picker, .hotel-charge-to-room-btn").remove();
            return;
        }
        attach_picker();
        attach_charge_btn();
        // apply launch preselection once per launch
        const launch = read_launch();
        if (launch && launch.reservation && !launch.applied && p.frm && p.frm.doc) {
            set_guest(launch.customer, launch.reservation);
            launch.applied = true;
            try { localStorage.setItem(LAUNCH_KEY, JSON.stringify(launch)); } catch (e) { /* ignore */ }
            $(".hotel-in-house-select").val(launch.reservation);
        }
        // keep reservation on new orders in sync with picker
        const sel = $(".hotel-in-house-select").val();
        if (sel && p.frm && p.frm.doc && !p.frm.doc.hotel_reservation) {
            const opt = $(".hotel-in-house-select option:selected");
            if (opt.data("customer") === p.frm.doc.customer) p.frm.doc.hotel_reservation = sel;
        }
    }

    function attach_picker() {
        const $sec = $(".customer-section");
        if (!$sec.length || $sec.find(".hotel-in-house-picker").length) return;
        const $picker = $(`
            <div class="hotel-in-house-picker">
                <label class="control-label small text-muted">${__("In-House Guest (Room)")}</label>
                <select class="hotel-in-house-select form-control input-sm">
                    <option value="">${__("-- Select In-House Guest --")}</option>
                </select>
            </div>`);
        $sec.prepend($picker);
        frappe.call({ method: "hospitality_core.pos.get_in_house_guests" }).then((r) => {
            const $s = $picker.find("select");
            (r.message || []).forEach((g) => {
                $s.append($("<option>").val(g.reservation).attr("data-customer", g.customer)
                    .text(`${__("Room")} ${g.room} · ${g.guest_name || g.customer} (${g.reservation})`));
            });
            const cur = current_reservation();
            if (cur) $s.val(cur);
            $s.on("change", function () {
                const opt = $(this).find("option:selected");
                set_guest(opt.data("customer"), $(this).val());
            });
        });
    }

    function attach_charge_btn() {
        const $submit = $(".pos-payment .submit-order-btn, .submit-order-btn").not(".hotel-charge-to-room-btn").first();
        if (!$submit.length || $submit.siblings(".hotel-charge-to-room-btn").length) return;
        const $btn = $(`<div class="hotel-charge-to-room-btn">${__("Charge to Room")}</div>`);
        $submit.after($btn);
        $btn.on("click", () => charge_to_room($btn));
    }

    async function charge_to_room($btn) {
        const p = pos();
        const frm = p && p.frm;
        if (!frm || !frm.doc) return frappe.msgprint(__("No active order found."));
        const reservation = $(".hotel-in-house-select").val() || frm.doc.hotel_reservation;
        if (!reservation) return frappe.msgprint(__("Select the In-House Guest (room) first."));
        if (!(frm.doc.items || []).length) return frappe.msgprint(__("Cart is empty."));

        frappe.confirm(
            __("Charge {0} to the room bill of reservation {1}? It will be billed at check-out.",
                [format_currency(frm.doc.grand_total, frm.doc.currency), reservation]),
            async () => {
                $btn.addClass("disabled");
                try {
                    frm.doc.hotel_reservation = reservation;
                    if (frm.is_new() || frm.is_dirty()) {
                        let failed = false;
                        await frm.save(null, null, null, () => (failed = true));
                        if (failed) return;
                    }
                    const r = await frappe.call({
                        method: "hospitality_core.pos.charge_to_room",
                        args: { invoice_name: frm.doc.name, reservation: reservation },
                        freeze: true,
                    });
                    if (r && r.message) {
                        frappe.show_alert({ message: __("Order {0} charged to room ({1}).", [r.message.invoice, r.message.reservation]), indicator: "orange" });
                        try { window.parent !== window && window.parent.postMessage({ type: "hotel_room_charge", data: r.message }, window.location.origin); } catch (e) { /* ignore */ }
                        await p.make_new_invoice();
                    }
                } finally {
                    $btn.removeClass("disabled");
                }
            }
        );
    }

    function start() {
        if (timer) return;
        frappe.db.get_single_value("Hotel Settings", "room_pos_profile").then((v) => {
            room_profile = v;
            timer = setInterval(() => {
                if ((frappe.get_route() || [])[0] !== "point-of-sale") return;
                try { tick(); } catch (e) { console.error("hotel pos tick", e); }
            }, 700);
        });
    }

    start();
})();
