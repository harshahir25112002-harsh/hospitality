frappe.ui.form.on("OTA Settings", {
	refresh(frm) {
		frm.trigger("render_buttons");

		if (frm.doc.connection_status === "Connected") {
			frm.dashboard.set_headline(
				`<span class="text-success">${__("Connected to OTA Server")}</span>`
			);
		} else if (frm.doc.connection_status === "Error") {
			frm.dashboard.set_headline(
				`<span class="text-danger">${__("Connection Error — check API URL and Key")}</span>`
			);
		}
	},

	render_buttons(frm) {
		if (frm.is_new()) return;

		// Test Connection button
		if (frm.doc.api_key && frm.doc.api_base_url) {
			frm.add_custom_button(__("Test Connection"), () => {
				frappe.call({
					method: "hospitality_core.hospitality_core.doctype.ota_settings.ota_settings.test_connection",
					freeze: true,
					freeze_message: __("Testing connection..."),
					callback: (r) => {
						if (r.message && r.message.status === "success") {
							frappe.msgprint({
								title: __("Connection Successful"),
								indicator: "green",
								message: r.message.message
							});

							if (r.message.properties && r.message.properties.length > 0 && !frm.doc.property_id) {
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
											frm.set_value("property_id", match[1]);
											frm.save();
										}
									},
									__("Select Property"),
									__("Set Property")
								);
							}
							frm.reload_doc();
						}
					}
				});
			}).addClass("btn-primary");

			// Fetch Bookings Now button
			frm.add_custom_button(__("Fetch Bookings Now"), () => {
				frappe.call({
					method: "hospitality_core.api.ota.pull_booking_revisions",
					freeze: true,
					freeze_message: __("Fetching bookings from OTA server..."),
					callback: (r) => {
						if (r.message) {
							frappe.show_alert({
								message: __("Fetched {0} new/updated bookings!", [r.message.processed || 0]),
								indicator: "green"
							});
							frm.reload_doc();
						}
					}
				});
			});
		}

		frm.add_custom_button(__("View OTA Reservations"), () => {
			frappe.set_route("List", "OTA Reservation");
		});
	}
});
