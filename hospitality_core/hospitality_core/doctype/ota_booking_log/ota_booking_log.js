frappe.ui.form.on("OTA Booking Log", {
	refresh(frm) {
		if (frm.doc.status === "New" || frm.doc.status === "Failed") {
			frm.add_custom_button(__("Process Booking"), () => {
				frappe.call({
					method: "hospitality_core.hospitality_core.doctype.ota_booking_log.ota_booking_log.process_booking_log",
					args: { log_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Creating reservation from OTA booking..."),
					callback: (r) => {
						if (r.message && r.message.reservation) {
							frappe.show_alert({
								message: __("Reservation {0} created!", [r.message.reservation]),
								indicator: "green"
							});
						}
						frm.reload_doc();
					}
				});
			}).addClass("btn-primary");
		}

		if (frm.doc.reservation) {
			frm.add_custom_button(__("View Reservation"), () => {
				frappe.set_route("Form", "Hotel Reservation", frm.doc.reservation);
			});
		}
	}
});

