app_name = "hospitality_core"
app_title = "Sky Hotel Management System"
app_publisher = "Sky Hotel Management"
app_description = "Sky Hotel Management System"
app_email = "info@skyhotel.com"
app_license = "gpl-2.0"

add_to_apps_screen = [
    {
        "name": "Hotel management",
        "logo": "/files/a-colorful-tropical-resort-hotel-logo-design-free-vector.jpg",
        "title": "Hotel Management System",
        "route": "/desk/hospitality-core/hotel",
        "setup_wizard_text": "Let's manage your hotel business.",
        "sequence_id": 2,
    }
]

# Expose hotel settings to client session
boot_session = "hospitality_core.utils.boot_session"

# Setup custom fields after install
after_install = "hospitality_core.setup.install.after_install"

# Document Events
extend_doctype_class = {"File": "hospitality_core.file_override.HospitalityFile"}

doc_events = {
    "Hotel Room": {
        "on_update": "hospitality_core.api.ota.on_hotel_room_change",
        "on_trash": "hospitality_core.api.ota.on_hotel_room_change"
    },
    "Hotel Reservation": {
        "on_update": "hospitality_core.api.ota.on_reservation_change",
        "on_cancel": "hospitality_core.api.ota.on_reservation_change"
    },
    "Room Rate Plan": {
        "on_update": "hospitality_core.api.ota.on_rate_plan_change",
        "on_trash": "hospitality_core.api.ota.on_rate_plan_change"
    },
    "Issue": {
        "on_update": "hospitality_core.maintenance.on_issue_update"
    },
    "Payment Entry": {
        "validate": "hospitality_core.integrations.razorpay.guards.validate_payment_entry"
    },
    "Sales Invoice": {
        "validate": "hospitality_core.pos.validate_sales_invoice",
        "before_submit": "hospitality_core.pos.before_submit_sales_invoice"
    }
}

# Standard Page Extensions
page_js = {
    "point-of-sale": "public/js/pos_extension.js"
}

doctype_js = {
    "Sales Invoice": "public/js/sales_invoice_razorpay.js"
}

# Flag rooms of today's arrivals as Reserved (future bookings no longer block rooms early)
scheduler_events = {
    "cron": {
        "*/5 * * * *": [
            "hospitality_core.integrations.razorpay.payments.expire_and_release"
        ],
        "*/15 * * * *": [
            "hospitality_core.api.ota.pull_booking_revisions"
        ]
    },
    "daily": [
        "hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation.mark_todays_arrivals",
        "hospitality_core.api.audit.run_night_audit"
    ]
}
