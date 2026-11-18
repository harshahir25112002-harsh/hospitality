"""Guest checkout page for Razorpay payment requests: /hotel-pay?token=<access token>.

The token is read by the page script and sent to hospitality_core.api.razorpay; nothing about the
payment is rendered server-side, so the HTML is identical (and cache-safe) for every visitor.
"""
import frappe

no_cache = 1
sitemap = 0


def get_context(context):
    hotel = frappe.get_cached_doc("Hotel Settings")
    context.no_breadcrumbs = 1
    context.no_header = 1
    context.title = f"Secure payment · {hotel.hotel_name}" if hotel.hotel_name else "Secure payment"
    context.metatags = {"robots": "noindex, nofollow"}
    return context
