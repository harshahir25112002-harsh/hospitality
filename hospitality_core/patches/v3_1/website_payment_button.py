"""Add a "Pay advance online" button to the booking confirmation of the DB-stored Web Page `home`.

The home page script lives only in the database (Web Page.javascript), so the change is a single,
marker-delimited insertion that can be removed with `revert()`:

    bench --site <site> execute hospitality_core.patches.v3_1.website_payment_button.revert

If the expected snippet is not found (the page was edited), nothing is changed and a note is logged;
the checkout itself (/hotel-pay) does not depend on this button.
"""
import frappe

PAGE = "home"
START, END = "/* hc-razorpay:start */", "/* hc-razorpay:end */"
ANCHOR = '(res.status === "Reserved" ? "Your room is reserved; payment is settled at the hotel." : "") + "</p>";'
REPLACEMENT = (
    '(res.status === "Reserved" ? (res.payment ? "" : "Your room is reserved; payment is settled at the hotel.") : "") + "</p>" +\n'
    "        " + START + " (res.payment && /^https?:\\/\\//.test(res.payment.url || \"\") ? ('<div style=\"margin-top:16px\">' +\n"
    "          '<p class=\"hotel-summary__note\">' + (res.payment.required\n"
    "            ? 'Please pay the advance of ' + esc(money(res.payment.amount)) + ' within ' + esc(String(res.payment.hold_minutes)) + ' minutes to keep this reservation.'\n"
    "            : 'You can pay an advance of ' + esc(money(res.payment.amount)) + ' securely online now, or settle at the hotel.') + '</p>' +\n"
    "          '<a class=\"hotel-btn hotel-btn--primary hotel-btn--block\" style=\"margin-top:8px\" href=\"' + esc(res.payment.url) + '\">Pay advance ' + esc(money(res.payment.amount)) + ' online</a>' +\n"
    "          '</div>') : \"\") " + END + ";"
)


def execute():
    js = frappe.db.get_value("Web Page", PAGE, "javascript")
    if not js or START in js:
        return
    if js.count(ANCHOR) != 1:
        frappe.log_error(title="Razorpay: home page payment button not installed",
                         message="Booking confirmation snippet not found in Web Page 'home'. Add the button manually.")
        return
    frappe.db.set_value("Web Page", PAGE, "javascript", js.replace(ANCHOR, REPLACEMENT), update_modified=False)
    frappe.clear_cache()


def revert():
    js = frappe.db.get_value("Web Page", PAGE, "javascript")
    if not js or START not in js:
        return
    if js.count(REPLACEMENT) == 1:
        frappe.db.set_value("Web Page", PAGE, "javascript", js.replace(REPLACEMENT, ANCHOR), update_modified=False)
        frappe.db.commit()
        frappe.clear_cache()
