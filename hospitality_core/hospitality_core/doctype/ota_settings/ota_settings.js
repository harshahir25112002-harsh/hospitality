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
							frm.reload_doc();
						}
					}
				});
			}).addClass("btn-primary");

			// Select Active Property from Channex
			frm.add_custom_button(__("Select Property"), () => {
				frappe.call({
					method: "hospitality_core.hospitality_core.doctype.ota_settings.ota_settings.get_channex_properties",
					freeze: true,
					freeze_message: __("Fetching properties from Channex..."),
					callback: (r) => {
						if (r.message && r.message.properties) {
							let props = r.message.properties;
							if (!props.length) {
								frappe.msgprint(__("No properties found in this Channex account."));
								return;
							}
							let options = props.map((p) => `${p.title} (${p.id})`);
							let currentVal = options.find(o => o.includes(frm.doc.property_id));
							frappe.prompt(
								[{
									label: __("Select Property to Connect"),
									fieldname: "property",
									fieldtype: "Select",
									options: options,
									default: currentVal || options[0],
									description: __("Select the Channex property you want to sync with ERPNext"),
									reqd: 1
								}],
								(values) => {
									let match = values.property.match(/\(([^)]+)\)$/);
									if (match) {
										frm.set_value("property_id", match[1]);
										frm.save().then(() => {
											frappe.show_alert({ message: __("Active property updated to {0}! Syncing room types...", [match[1]]), indicator: "green" });
											frappe.call({
												method: "hospitality_core.hospitality_core.doctype.ota_settings.ota_settings.fetch_room_types_from_ota",
												freeze: true,
												freeze_message: __("Syncing room types for new property..."),
												callback: () => frm.reload_doc()
											});
										});
									}
								},
								__("Select Active Channex Property"),
								__("Save & Sync Rooms")
							);
						}
					}
				});
			});

			
			// Fetch Rooms from OTA button
			frm.add_custom_button(__("Fetch Rooms from OTA"), () => {
				frappe.call({
					method: "hospitality_core.hospitality_core.doctype.ota_settings.ota_settings.fetch_room_types_from_ota",
					freeze: true,
					freeze_message: __("Fetching room types and rooms from OTA..."),
					callback: (r) => {
						if (r.message && r.message.status === "success") {
							frappe.msgprint({
								title: __("Rooms Fetched"),
								indicator: "green",
								message: r.message.message
							});
						}
					}
				});
			});

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
