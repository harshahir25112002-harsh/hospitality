// Sales Invoice: collect the outstanding amount through Razorpay (Hospitality Core).
// The server validates eligibility and the amount; the invoice is paid only after Razorpay verification.
frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || frm.doc.is_return || !(frm.doc.outstanding_amount > 0)) return;
		frappe.call({ method: "hospitality_core.api.razorpay.get_front_desk_config", silent: true }).then((r) => {
			const c = r.message || {};
			if (!c.invoice) return;
			frm.add_custom_button(__("Collect via Razorpay"), () => hc_rzp_invoice_dialog(frm), __("Create"));
		}).catch(() => {});
	},
});

function hc_rzp_invoice_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Razorpay payment for {0}", [frm.doc.name]),
		fields: [
			{ fieldtype: "Data", fieldname: "customer", label: __("Customer"), read_only: 1, default: frm.doc.customer_name || frm.doc.customer },
			{ fieldtype: "Currency", fieldname: "amount", label: __("Amount"), reqd: 1, default: frm.doc.outstanding_amount,
			  description: __("Outstanding: {0}. Partial payments only if allowed in Payment Gateway settings.", [format_currency(frm.doc.outstanding_amount, frm.doc.currency)]) },
		],
		primary_action_label: __("Create Payment Request"),
		primary_action(v) {
			frappe.call({
				method: "hospitality_core.api.razorpay.create_invoice_payment_request",
				args: { sales_invoice: frm.doc.name, amount: v.amount, idempotency_key: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())) },
				freeze: true,
			}).then((r) => {
				d.hide();
				hc_rzp_show_handoff(frm, r.message);
			});
		},
	});
	d.show();
}

function hc_rzp_show_handoff(frm, r) {
	const esc = frappe.utils.escape_html;
	const t = r.transaction;
	const d = new frappe.ui.Dialog({
		title: __("Online Payment · {0}", [t.name]),
		fields: [{ fieldtype: "HTML", fieldname: "h" }],
		primary_action_label: __("Open checkout"),
		primary_action: () => window.open(r.pay_url, "hc_rzp_checkout", "popup,width=520,height=760"),
	});
	d.fields_dict.h.$wrapper.html(`
		<div class="text-center">${r.qr_svg ? `<div style="display:inline-block;background:#fff;padding:8px;border-radius:8px">${r.qr_svg}</div>` : ""}</div>
		<div class="input-group mt-3"><input class="form-control" readonly value="${esc(r.pay_url)}">
			<button class="btn btn-default hc-copy">${__("Copy")}</button></div>
		<div class="mt-3"><span class="indicator-pill blue hc-status">${__("Waiting for payment…")}</span></div>`);
	d.$wrapper.find(".hc-copy").on("click", () => frappe.utils.copy_to_clipboard(r.pay_url));
	const timer = setInterval(() => {
		frappe.call({ method: "hospitality_core.api.razorpay.get_transaction_status", args: { name: t.name }, silent: true }).then((s) => {
			const st = s.message.status;
			d.$wrapper.find(".hc-status").text(__(st)).toggleClass("green", st === "Reconciled").toggleClass("red", st === "Failed");
			if (st === "Reconciled") { clearInterval(timer); frm.reload_doc(); }
		});
	}, 5000);
	d.onhide = () => clearInterval(timer);
	d.show();
}
