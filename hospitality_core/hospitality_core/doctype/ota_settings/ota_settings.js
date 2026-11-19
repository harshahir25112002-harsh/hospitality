frappe.ui.form.on("OTA Settings", {
	refresh(frm) {
		frm.trigger("render_buttons");

		if (frm.doc.environment === "Production" && frm.doc.connection_status !== "Connected") {
			frm.dashboard.set_headline(
				`<span class="text-warning">${__("Production mode — not yet connected to Channex")}</span>`
			);
		} else if (frm.doc.connection_status === "Connected") {
			frm.dashboard.set_headline(
				`<span class="text-success">${__("Connected to Channex ({0})", [frm.doc.environment])}</span>`
			);
		}
	},

	environment(frm) {
		if (frm.doc.environment === "Staging") {
			frm.set_value("api_base_url", "https://staging.channex.io/api/v1");
		} else {
			frm.set_value("api_base_url", "https://app.channex.io/api/v1");
		}
	},

	render_buttons(frm) {
		if (frm.is_new()) return;

		// Primary Action: Test Connection
		if (frm.doc.api_key) {
			frm.add_custom_button(__("Test Connection"), () => {
				frappe.call({
					method: "hospitality_core.hospitality_core.doctype.ota_settings.ota_settings.test_connection",
					freeze: true,
					freeze_message: __("Testing Channex connection..."),
					callback: (r) => {
						if (r.message && r.message.status === "success") {
							frappe.msgprint({
								title: __("Connection Successful"),
								indicator: "green",
								message: r.message.message
							});

							if (r.message.properties && r.message.properties.length > 0 && !frm.doc.channex_property_id) {
								let options = r.message.properties.map(
									(p) => `${p.title} (${p.id})`
								);
								frappe.prompt(
									[{
										label: __("Select Property"),
										fieldname: "property",
										fieldtype: "Select",
										options: options,
										reqd: 1
									}],
									(values) => {
										let match = values.property.match(/\(([^)]+)\)$/);
										if (match) {
											frm.set_value("channex_property_id", match[1]);
											frm.set_value("channex_property_name", values.property.replace(` (${match[1]})`, ""));
											frm.save();
										}
									},
									__("Select Your Property"),
									__("Set Property")
								);
							}
							frm.reload_doc();
						}
					}
				});
			}).addClass("btn-primary");
		}

		// Webhook Actions
		if (frm.doc.channex_property_id && frm.doc.api_key) {
			frm.add_custom_button(__("Register Webhook"), () => {
				frappe.call({
					method: "hospitality_core.api.ota.register_webhook",
					freeze: true,
					freeze_message: __("Registering webhook on Channex..."),
					callback: (r) => {
						if (r.message && r.message.status === "success") {
							frappe.show_alert({
								message: __("Webhook registered on Channex successfully!"),
								indicator: "green"
							});
							frm.reload_doc();
						}
					}
				});
			}, __("Actions"));
		}

		if (frm.doc.webhook_url) {
			frm.add_custom_button(__("Copy Webhook URL"), () => {
				frappe.utils.copy_to_clipboard(frm.doc.webhook_url);
				frappe.show_alert({message: __("Webhook URL copied!"), indicator: "green"});
			}, __("Actions"));
		}

		// Sync Actions
		if (frm.doc.channex_property_id && frm.doc.api_key) {
			frm.add_custom_button(__("Push Availability Now"), () => {
				frappe.call({
					method: "hospitality_core.api.ota.push_availability",
					freeze: true,
					freeze_message: __("Pushing room availability to Channex..."),
					callback: (r) => {
						if (r.message && r.message.status === "success") {
							frappe.show_alert({
								message: __("Pushed {0} availability records!", [r.message.pushed_records]),
								indicator: "green"
							});
							frm.reload_doc();
						}
					}
				});
			}, __("Sync"));

			frm.add_custom_button(__("Push Rates Now"), () => {
				frappe.call({
					method: "hospitality_core.api.ota.push_rates",
					freeze: true,
					freeze_message: __("Pushing rates to Channex..."),
					callback: (r) => {
						if (r.message && r.message.status === "success") {
							frappe.show_alert({
								message: __("Pushed {0} rate records!", [r.message.records]),
								indicator: "green"
							});
							frm.reload_doc();
						}
					}
				});
			}, __("Sync"));

			frm.add_custom_button(__("Pull Bookings Now"), () => {
				frappe.call({
					method: "hospitality_core.api.ota.pull_booking_revisions",
					freeze: true,
					freeze_message: __("Checking Channex feed for new bookings..."),
					callback: (r) => {
						if (r.message && r.message.status === "success") {
							frappe.show_alert({
								message: __("Pull complete! Processed {0} bookings.", [r.message.processed]),
								indicator: "green"
							});
							frm.reload_doc();
						}
					}
				});
			}, __("Sync"));
		}
	}
});
