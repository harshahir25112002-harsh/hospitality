frappe.listview_settings["OTA Booking Log"] = {
	add_fields: ["status", "ota_source"],
	get_indicator: function (doc) {
		var colors = {
			"New": "blue",
			"Acknowledged": "orange",
			"Processed": "green",
			"Failed": "red",
			"Cancelled": "gray",
			"Modified": "yellow"
		};
		return [__(doc.status), colors[doc.status] || "grey", "status,=," + doc.status];
	}
};

