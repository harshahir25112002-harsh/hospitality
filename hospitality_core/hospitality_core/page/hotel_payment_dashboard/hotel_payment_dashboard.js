// Online Payments (Razorpay) — transaction monitoring for Hospitality Core.
// There is intentionally no way to mark a transaction as paid from here: only Razorpay-verified
// payments are recorded. Staff can re-check a transaction with Razorpay or retry posting the
// Payment Entry of an already-captured payment.
const HPD = "hospitality_core.api.razorpay.";

frappe.pages["hotel-payment-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Online Payments"), single_column: true });
	wrapper.hpd = new HotelPaymentDashboard(page);
};
frappe.pages["hotel-payment-dashboard"].on_page_show = function (wrapper) {
	wrapper.hpd && wrapper.hpd.refresh();
};

class HotelPaymentDashboard {
	constructor(page) {
		this.page = page;
		this.make_filters();
		this.$body = $(`<div class="hpd">
			<style>
				.hpd-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:8px 0 16px}
				.hpd-card{border:1px solid var(--border-color);border-radius:10px;padding:12px 14px;background:var(--card-bg);cursor:pointer}
				.hpd-card .v{font-size:20px;font-weight:600}
				.hpd-card .a{font-size:12px;color:var(--text-muted)}
				.hpd-card .l{font-size:12px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em}
				.hpd-table-wrap{overflow-x:auto;border:1px solid var(--border-color);border-radius:10px}
				.hpd-table{width:100%;font-size:13px;margin:0}
				.hpd-table th{background:var(--subtle-fg);font-weight:600;white-space:nowrap}
				.hpd-table td,.hpd-table th{padding:8px 10px;border-bottom:1px solid var(--border-color)}
				.hpd-table tr.hpd-row{cursor:pointer}
				.hpd-table tr.hpd-row:hover{background:var(--subtle-accent)}
				.hpd-empty{padding:40px;text-align:center;color:var(--text-muted)}
				.hpd-mono{font-family:var(--font-stack-monospace,monospace);font-size:12px}
			</style>
			<div class="hpd-cards"></div>
			<div class="hpd-table-wrap"></div>
		</div>`).appendTo(page.main);
		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_menu_item(__("Gateway Settings"), () => frappe.set_route("Form", "Hotel Payment Gateway Settings"));
		this.page.add_menu_item(__("Webhook Log"), () => frappe.set_route("List", "Hotel Payment Webhook Log"));
		this.$body.on("click", ".hpd-row", (e) => this.show_detail($(e.currentTarget).data("name")));
		this.$body.on("click", ".hpd-card", (e) => {
			const st = $(e.currentTarget).data("status");
			this.fields.status.set_value(st || "");
		});
		frappe.realtime.on("hotel_payment_update", frappe.utils.debounce(() => this.refresh(), 800));
		this.refresh();
	}

	make_filters() {
		const p = this.page, on = () => this.refresh();
		const STATUSES = ["", "Initiated", "Order Created", "Payment Pending", "Authorized", "Captured", "Failed", "Cancelled", "Expired",
			"Refund Pending", "Partially Refunded", "Refunded", "Reconciliation Pending", "Reconciled"];
		this.fields = {
			dates: p.add_field({ fieldname: "dates", label: __("Date Range"), fieldtype: "DateRange", change: on,
				default: [frappe.datetime.add_days(frappe.datetime.get_today(), -30), frappe.datetime.get_today()] }),
			customer: p.add_field({ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer", change: on }),
			hotel_reservation: p.add_field({ fieldname: "hotel_reservation", label: __("Reservation"), fieldtype: "Link", options: "Hotel Reservation", change: on }),
			status: p.add_field({ fieldname: "status", label: __("Status"), fieldtype: "Select", options: STATUSES, change: on }),
			environment: p.add_field({ fieldname: "environment", label: __("Environment"), fieldtype: "Select", options: ["", "Test", "Live"], change: on }),
			min_amount: p.add_field({ fieldname: "min_amount", label: __("Min Amount"), fieldtype: "Currency", change: on }),
			max_amount: p.add_field({ fieldname: "max_amount", label: __("Max Amount"), fieldtype: "Currency", change: on }),
			razorpay_payment_id: p.add_field({ fieldname: "razorpay_payment_id", label: __("Razorpay Payment ID"), fieldtype: "Data", change: on }),
		};
	}

	filters() {
		const f = {};
		Object.entries(this.fields).forEach(([k, fld]) => {
			const v = fld.get_value();
			if (k === "dates") { if (v && v.length) { f.from_date = v[0]; f.to_date = v[1]; } }
			else if (v) f[k] = v;
		});
		return f;
	}

	refresh() {
		if (this._loading) return;
		this._loading = true;
		frappe.call({ method: HPD + "get_dashboard_data", args: { filters: this.filters() } })
			.then((r) => this.render(r.message))
			.finally(() => (this._loading = false));
	}

	render(data) {
		this.can_refund = data.can_refund;
		const esc = frappe.utils.escape_html;
		const money = (v) => format_currency(v, frappe.defaults.get_default("currency"));
		const cards = [
			["initiated", __("Initiated"), ""], ["captured", __("Captured"), "Captured"], ["failed", __("Failed"), "Failed"],
			["pending", __("Pending"), "Payment Pending"], ["refunded", __("Refunded"), "Refunded"], ["reconciled", __("Reconciled"), "Reconciled"],
		];
		this.$body.find(".hpd-cards").html(cards.map(([k, l, st]) => `
			<div class="hpd-card" data-status="${st}"><div class="l">${l}</div><div class="v">${data.totals[k]}</div><div class="a">${money(data.amounts[k])}</div></div>`).join(""));
		if (!data.rows.length) {
			this.$body.find(".hpd-table-wrap").html(`<div class="hpd-empty">${__("No online payment transactions match these filters.")}</div>`);
			return;
		}
		this.$body.find(".hpd-table-wrap").html(`<table class="hpd-table"><thead><tr>
			<th>${__("Created")}</th><th>${__("Transaction")}</th><th>${__("Status")}</th><th>${__("Customer")}</th><th>${__("Reservation / Invoice")}</th>
			<th>${__("Razorpay Payment ID")}</th><th>${__("Method")}</th><th>${__("Payment Entry")}</th><th class="text-right">${__("Amount")}</th></tr></thead>
			<tbody>${data.rows.map((r) => `<tr class="hpd-row" data-name="${esc(r.name)}">
				<td>${esc(frappe.datetime.str_to_user(r.creation))}</td>
				<td>${esc(r.name)}${r.environment === "Test" ? ` <span class="indicator-pill orange">${__("Test")}</span>` : ""}${r.needs_review ? ` <span class="indicator-pill red">${__("Review")}</span>` : ""}</td>
				<td>${hpd_pill(r.status)}</td>
				<td>${esc(r.customer_name || r.customer || "")}</td>
				<td>${esc(r.sales_invoice || r.hotel_reservation || (r.scenario === "Gateway Test" ? __("Gateway test") : ""))}</td>
				<td class="hpd-mono">${esc(r.razorpay_payment_id || "")}</td>
				<td>${esc(r.payment_method || "")}</td>
				<td>${esc(r.payment_entry || "")}</td>
				<td class="text-right">${format_currency(r.amount, r.currency)}</td></tr>`).join("")}</tbody></table>`);
	}

	show_detail(name) {
		frappe.call({ method: HPD + "get_transaction_detail", args: { name } }).then((r) => this.detail_dialog(r.message));
	}

	detail_dialog(t) {
		const me = this, esc = frappe.utils.escape_html;
		const link = (dt, n) => (n ? `<a href="/desk/${frappe.router.slug(dt)}/${encodeURIComponent(n)}" target="_blank">${esc(n)}</a>` : "—");
		const dt = (v) => (v ? esc(frappe.datetime.str_to_user(v)) : "—");
		const row = (k, v) => `<tr><th style="width:40%">${k}</th><td>${v}</td></tr>`;
		const d = new frappe.ui.Dialog({ title: `${t.name} · ${t.status}`, size: "large", fields: [{ fieldtype: "HTML", fieldname: "h" }] });
		const refunds = (t.refunds || []).map((x) => `<tr><td class="hpd-mono">${esc(x.razorpay_refund_id || "")}</td><td>${esc(x.status)}</td>
			<td>${link("Payment Entry", x.payment_entry)}</td><td>${esc(x.reason || "")}</td><td class="text-right">${format_currency(x.amount, t.currency)}</td></tr>`).join("");
		const hooks = (t.webhooks || []).map((w) => `<tr><td>${esc(w.event)}</td><td>${esc(w.status)}</td><td>${dt(w.received_on)}</td><td>${esc(w.message || "")}</td></tr>`).join("");
		d.fields_dict.h.$wrapper.html(`
			${t.needs_review ? `<div class="alert alert-warning">${esc(t.review_note || "")}</div>` : ""}
			${t.failure_reason ? `<div class="alert alert-secondary small">${esc(t.failure_reason)}</div>` : ""}
			<table class="table table-sm">
				${row(__("Status"), hpd_pill(t.status))}
				${row(__("Scenario / Source"), esc(`${t.scenario} · ${t.source || ""} · ${t.environment}`))}
				${row(__("Customer"), link("Customer", t.customer))}
				${row(__("Reservation"), link("Hotel Reservation", t.hotel_reservation))}
				${row(__("Sales Invoice"), link("Sales Invoice", t.sales_invoice))}
				${row(__("Amount / Captured / Refunded"), `${format_currency(t.amount, t.currency)} / ${format_currency(t.captured_amount || 0, t.currency)} / ${format_currency(t.refunded_amount || 0, t.currency)}`)}
				${row(__("Razorpay Order ID"), `<span class="hpd-mono">${esc(t.razorpay_order_id || "—")}</span>`)}
				${row(__("Razorpay Payment ID"), `<span class="hpd-mono">${esc(t.razorpay_payment_id || "—")}</span>`)}
				${row(__("Payment method / reference"), esc(`${t.payment_method || "—"} ${t.gateway_reference ? "· " + t.gateway_reference : ""}`))}
				${row(__("Payment Entry (reconciliation)"), t.payment_entry ? link("Payment Entry", t.payment_entry) : `<span class="text-muted">${__("Not reconciled")}</span>`)}
				${row(__("Created / Verified"), `${dt(t.created_at)} / ${dt(t.verified_at)}`)}
				${row(__("Captured / Reconciled"), `${dt(t.captured_at)} / ${dt(t.reconciled_at)}`)}
			</table>
			${refunds ? `<h6>${__("Refunds")}</h6><table class="table table-sm">${refunds}</table>` : ""}
			${hooks ? `<h6>${__("Webhook events")}</h6><table class="table table-sm small">${hooks}</table>` : ""}
			<div class="hpd-actions d-flex flex-wrap" style="gap:8px"></div>
			<div class="text-muted small mt-3">${__("Captured by Razorpay ≠ settled to your bank: funds stay in the Razorpay clearing account until the settlement is booked.")}</div>`);
		const $a = d.fields_dict.h.$wrapper.find(".hpd-actions");
		const btn = (label, cls, fn) => $(`<button class="btn btn-sm ${cls}">${label}</button>`).appendTo($a).on("click", fn);
		const after = () => { d.hide(); me.refresh(); me.show_detail(t.name); };
		if (["Captured", "Reconciliation Pending"].includes(t.status) && !t.payment_entry) {
			btn(__("Retry Reconciliation"), "btn-primary", () => frappe.call({ method: HPD + "retry_reconciliation", args: { name: t.name }, freeze: true }).then(after));
		}
		if (t.razorpay_order_id && !["Reconciled", "Refunded", "Partially Refunded", "Refund Pending"].includes(t.status)) {
			btn(__("Check with Razorpay"), "btn-default", () => frappe.call({ method: HPD + "sync_transaction", args: { name: t.name }, freeze: true }).then(after));
		}
		if (this.can_refund && t.refundable > 0) {
			btn(__("Refund…"), "btn-danger", () => {
				frappe.prompt([
					{ fieldname: "amount", fieldtype: "Currency", label: __("Refund amount (max {0})", [format_currency(t.refundable, t.currency)]), reqd: 1, default: t.refundable },
					{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
				], (v) => {
					frappe.confirm(__("Refund {0} to the guest through Razorpay? This cannot be undone.", [format_currency(v.amount, t.currency)]), () => {
						frappe.call({ method: HPD + "refund_transaction", args: { name: t.name, amount: v.amount, reason: v.reason }, freeze: true }).then(after);
					});
				}, __("Refund payment"), __("Continue"));
			});
		}
		if (this.can_refund && t.status === "Refund Pending") {
			btn(__("Update refund status"), "btn-default", () => frappe.call({ method: HPD + "sync_refunds", args: { name: t.name }, freeze: true }).then(after));
		}
		btn(__("Open document"), "btn-default", () => frappe.set_route("Form", "Hotel Payment Transaction", t.name));
		d.show();
	}
}

function hpd_pill(status) {
	const c = { Reconciled: "green", Captured: "green", Failed: "red", Cancelled: "gray", Expired: "gray", Authorized: "orange",
		"Reconciliation Pending": "orange", "Refund Pending": "purple", "Partially Refunded": "purple", Refunded: "purple" }[status] || "blue";
	return `<span class="indicator-pill ${c}">${frappe.utils.escape_html(__(status))}</span>`;
}
