frappe.ui.form.on("OTA Reservation", {
	refresh(frm) {
		if (frm.doc.hotel_reservation) {
			frm.add_custom_button(__("View Hotel Reservation"), () => {
				frappe.set_route("Form", "Hotel Reservation", frm.doc.hotel_reservation);
			}).addClass("btn-primary");
		} else if (frm.doc.status !== "Cancelled" && !frm.is_new()) {
			frm.add_custom_button(__("Accept & Create Hotel Reservation"), () => {
				frappe.confirm(
					__("Accept this OTA booking for {0} ({1} to {2}) and create a Hotel Reservation?", [
						frm.doc.guest_name,
						frm.doc.check_in_date,
						frm.doc.check_out_date
					]),
					() => {
						frappe.call({
							method: "hospitality_core.api.console.accept_ota_booking",
							args: { ota_reservation_name: frm.doc.name },
							freeze: true,
							freeze_message: __("Accepting booking..."),
							callback: (r) => {
								if (r.message && r.message.status === "success") {
									frappe.show_alert({
										message: r.message.message,
										indicator: "green"
									});
									frm.reload_doc();
								}
							}
						});
					}
				);
			}).addClass("btn-primary");
		}
	}
});
