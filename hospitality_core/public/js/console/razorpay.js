/**
 * Front Desk Console - Razorpay online payments. Mixed into FrontDeskConsole.prototype.
 *
 * Staff never mark an online payment as paid: they create a payment request, hand the secure
 * checkout to the guest (QR / link / this screen), and the status shown here comes from the server,
 * which only records a payment after Razorpay verification.
 */
const FD_RZP = "hospitality_core.api.razorpay.";

Object.assign(FrontDeskConsole.prototype, {

    rzp_config() {
        if (this._rzp_config) return Promise.resolve(this._rzp_config);
        return FD.call(FD_RZP + "get_front_desk_config", {})
            .then((c) => (this._rzp_config = c || {}))
            .catch(() => (this._rzp_config = {}));
    },

    /** Called from dialog_receive_payment after the amount is known. */
    start_online_payment(target, amount, guest) {
        const me = this;
        const key = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()) + Math.random();
        const call = target.sales_invoice
            ? FD.call(FD_RZP + "create_invoice_payment_request", { sales_invoice: target.sales_invoice, amount, idempotency_key: key }, { freeze: true })
            : FD.call(FD_RZP + "create_reservation_payment_request", { reservation: target.reservation, amount, idempotency_key: key }, { freeze: true });
        return call.then((r) => me.dialog_online_handoff(r, guest));
    },

    dialog_online_handoff(r, guest) {
        const me = this;
        const t = r.transaction;
        const ref = t.sales_invoice || t.hotel_reservation;
        let done = false;
        const d = FD.dialog({
            title: __("Online Payment · {0}", [ref]),
            fields: [{ fieldtype: "HTML", fieldname: "body" }],
            primary_action_label: __("Open checkout on this screen"),
            primary_action() { window.open(r.pay_url, "fd_rzp_checkout", "popup,width=520,height=760"); },
            secondary_action_label: __("Cancel request"),
            secondary_action() {
                frappe.confirm(__("Cancel this payment request? A payment the guest already completed is still recorded."), () => {
                    FD.call(FD_RZP + "cancel_payment_request", { name: t.name }).then((s) => {
                        render(s);
                        if (s.status === "Cancelled") { stop(); d.hide(); frappe.show_alert({ message: __("Payment request cancelled"), indicator: "orange" }); }
                    });
                });
            },
        });
        const $b = d.fields_dict.body.$wrapper;
        $b.html(`
            <div class="fd-rzp">
                <div class="fd-rzp-test">${t.environment === "Test" ? __("TEST MODE") : ""}</div>
                ${FD.kv([[__("Guest"), guest || t.customer_name || t.customer], [__("Reference"), ref], [__("Amount"), FD.money(t.amount)], [__("Request"), t.name]])}
                <div class="fd-rzp-status"></div>
                <div class="fd-rzp-handoff">
                    ${r.qr_svg ? `<div class="fd-rzp-qr">${r.qr_svg}</div>` : ""}
                    <div class="fd-rzp-link">
                        <div class="text-muted small mb-1">${__("Guest scans the QR code, or open the secure checkout on this screen if the guest is at the desk.")}</div>
                        <div class="input-group"><input class="form-control input-sm" readonly value="${FD.esc(r.pay_url)}">
                            <button class="btn btn-default btn-sm fd-rzp-copy">${__("Copy link")}</button></div>
                        <div class="text-muted small mt-2">${__("Link valid until {0}. Payment is confirmed automatically after Razorpay verification.", [frappe.datetime.str_to_user(t.expires_on)])}</div>
                    </div>
                </div>
            </div>`);
        $b.find(".fd-rzp-copy").on("click", () => frappe.utils.copy_to_clipboard(r.pay_url));

        const render = (s) => {
            const map = {
                Reconciled: ["green", __("Paid · recorded as {0}", [s.payment_entry || ""])],
                Captured: ["green", __("Paid · posting Payment Entry…")],
                "Reconciliation Pending": ["orange", __("Paid · accounting entry pending (see Online Payments dashboard)")],
                Authorized: ["orange", __("Authorized · awaiting capture")],
                Failed: ["red", __("Last attempt failed: {0}. The guest can retry with the same link.", [s.failure_reason || ""])],
                Cancelled: ["gray", __("Cancelled")],
                Expired: ["gray", __("Expired")],
            };
            const [color, text] = map[s.status] || ["blue", __("Waiting for the guest to pay…")];
            $b.find(".fd-rzp-status").html(`<div class="fd-rzp-pill indicator-pill ${color}">${FD.esc(text)}</div>
                ${s.needs_review ? `<div class="fd-note">${FD.esc(s.review_note || "")}</div>` : ""}`);
            if (["Reconciled", "Captured", "Reconciliation Pending"].includes(s.status) && !done) {
                done = true;
                stop();
                d.set_primary_action(__("Close"), () => d.hide());
                d.get_secondary_btn().hide();
                frappe.show_alert({ message: __("Online payment of {0} received", [FD.money(s.amount)]), indicator: "green" });
                me.load_data(true);
            }
        };
        const poll = () => FD.call(FD_RZP + "get_transaction_status", { name: t.name }).then(render).catch(() => {});
        const timer = setInterval(poll, 4000);
        const on_rt = (data) => { if (data && data.name === t.name) poll(); };
        frappe.realtime.on("hotel_payment_update", on_rt);
        const stop = () => { clearInterval(timer); frappe.realtime.off("hotel_payment_update", on_rt); };
        d.onhide = stop;
        render(t);
        d.show();
    },

    /** Online payment requests for the reservation detail dialog. */
    render_online_payments($target, reservation) {
        FD.call(FD_RZP + "get_online_payments", { reservation }).then((rows) => {
            if (!rows || !rows.length) return;
            const color = { Reconciled: "green", Captured: "green", Failed: "red", Cancelled: "gray", Expired: "gray",
                "Reconciliation Pending": "orange", Authorized: "orange", Refunded: "purple", "Partially Refunded": "purple" };
            $target.html(`<div class="fd-sec-title">${__("Online Payments (Razorpay)")}</div>
                <table class="table table-sm fd-mini"><tbody>${rows.map((p) => `<tr>
                    <td>${FD.date(p.creation)}</td><td>${fd_doc_link("Hotel Payment Transaction", p.name)}</td>
                    <td><span class="indicator-pill ${color[p.status] || "blue"}">${FD.esc(__(p.status))}</span></td>
                    <td>${FD.esc(p.razorpay_payment_id || "")}</td><td class="text-right">${FD.money(p.amount)}</td></tr>`).join("")}</tbody></table>`);
        }).catch(() => {});
    },
});
