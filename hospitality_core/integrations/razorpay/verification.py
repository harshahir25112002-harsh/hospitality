"""Signature verification and independent payment-state confirmation."""
import hashlib
import hmac

from frappe.utils import flt

ID_PREFIX = {"order": "order_", "payment": "pay_", "refund": "rfnd_"}


def _hmac(secret, message):
    return hmac.new(secret.encode(), message if isinstance(message, bytes) else message.encode(), hashlib.sha256).hexdigest()


def verify_checkout_signature(order_id, payment_id, signature, key_secret):
    """Standard Checkout: HMAC_SHA256(order_id + "|" + payment_id, key_secret)."""
    if not (order_id and payment_id and signature and key_secret):
        return False
    return hmac.compare_digest(_hmac(key_secret, f"{order_id}|{payment_id}"), str(signature))


def verify_webhook_signature(raw_body: bytes, signature, webhook_secret):
    """Webhooks: HMAC_SHA256(raw request body, webhook secret) in X-Razorpay-Signature."""
    if not (raw_body and signature and webhook_secret):
        return False
    return hmac.compare_digest(_hmac(webhook_secret, raw_body), str(signature))


def valid_id(kind, value):
    v = str(value or "")
    return v.startswith(ID_PREFIX[kind]) and 8 <= len(v) <= 40 and v.replace("_", "").isalnum()


def to_paise(amount):
    return int(round(flt(amount) * 100))


def from_paise(paise):
    return flt(int(paise or 0) / 100.0, 2)


def check_payment_matches(payment, txn):
    """Compare a Razorpay payment entity (fetched from the API, not from the browser) with the
    transaction. Returns a list of problems; empty means it belongs to this transaction."""
    problems = []
    if payment.get("order_id") != txn.razorpay_order_id:
        problems.append("order mismatch")
    if int(payment.get("amount") or 0) != to_paise(txn.amount):
        problems.append("amount mismatch")
    if (payment.get("currency") or "").upper() != (txn.currency or "").upper():
        problems.append("currency mismatch")
    return problems


def payment_summary(payment):
    """Minimal, non-sensitive fields kept from a payment entity (no card / VPA / contact data)."""
    method = payment.get("method") or ""
    ref = (payment.get("acquirer_data") or {}).get("rrn") or (payment.get("acquirer_data") or {}).get("bank_transaction_id")
    return {
        "id": payment.get("id"),
        "status": payment.get("status"),
        "method": method,
        "amount": int(payment.get("amount") or 0),
        "currency": payment.get("currency"),
        "captured": bool(payment.get("captured")),
        "error": (payment.get("error_description") or payment.get("error_reason") or "")[:240],
        "reference": str(ref)[:60] if ref else None,
        "created_at": payment.get("created_at"),
    }
