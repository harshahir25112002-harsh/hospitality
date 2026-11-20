frappe.listview_settings["OTA Reservation"] = {
	add_fields: ["status", "channel_name", "total_amount"],
	get_indicator: function (doc) {
		var colors = {
			"New": "blue",
			"Confirmed": "green",
			"Modified": "orange",
			"Cancelled": "red"
		};
		return [__(doc.status), colors[doc.status] || "grey", "status,=," + doc.status];
	}
};
