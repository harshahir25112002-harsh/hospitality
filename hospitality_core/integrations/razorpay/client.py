"""Server-side Razorpay REST client.

Credentials are read from the encrypted Password fields of Hotel Payment Gateway Settings and are
only ever used here, as HTTP Basic auth towards https://api.razorpay.com/v1/. Nothing in this module
logs or returns secrets, request headers or raw card data.
"""
from contextlib import contextmanager

import frappe
import requests
from frappe import _

API_BASE = "https://api.razorpay.com/v1/"
TIMEOUT = (5, 20)  # connect, read seconds
SETTINGS = "Hotel Payment Gateway Settings"
KEY_PREFIX = {"Test": "rzp_test_", "Live": "rzp_live_"}


class RazorpayError(frappe.ValidationError):
    """Gateway rejected the request or could not be reached. Message is safe to show."""

    def __init__(self, message, status_code=None, code=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class GatewayDisabled(frappe.ValidationError):
    http_status_code = 503


def get_settings():
    # never the cached doc: credentials and the enabled flag must reflect the latest commit
    return frappe.get_doc(SETTINGS)


class Credentials:
    __slots__ = ("environment", "key_id", "_secret", "_webhook_secret")

    def __init__(self, environment, key_id, secret, webhook_secret):
        self.environment = environment
        self.key_id = key_id
        self._secret = secret
        self._webhook_secret = webhook_secret

    @property
    def secret(self):
        return self._secret

    @property
    def webhook_secret(self):
        return self._webhook_secret

    def __repr__(self):  # never leak secrets through tracebacks / logs
        return f"<Razorpay Credentials {self.environment} {self.key_id or '-'}>"


def get_credentials(settings=None, require_secret=True):
    s = settings or get_settings()
    env = s.environment or "Test"
    if env != "Test":
        frappe.throw(_("Razorpay Live Mode is not activated on this system."), GatewayDisabled)
    key_id = (s.test_key_id or "").strip()
    secret = s.get_password("test_key_secret", raise_exception=False) if s.test_key_secret else None
    webhook_secret = s.get_password("test_webhook_secret", raise_exception=False) if s.test_webhook_secret else None
    if require_secret and not (key_id and secret):
        frappe.throw(_("Razorpay API credentials are not configured."), GatewayDisabled)
    if key_id and not key_id.startswith(KEY_PREFIX[env]):
        frappe.throw(_("The configured Key ID does not belong to Razorpay {0} Mode.").format(env), GatewayDisabled)
    return Credentials(env, key_id, secret, webhook_secret)


def require_enabled(settings=None):
    s = settings or get_settings()
    if not s.enabled:
        frappe.throw(_("Online payments are not available at the moment."), GatewayDisabled)
    return s


def _error_message(resp):
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        err = {}
    code = err.get("code")
    desc = err.get("description") or ""
    if resp.status_code == 401:
        return _("Razorpay rejected the API credentials (authentication failed)."), code
    return (desc[:300] or _("Razorpay returned HTTP {0}.").format(resp.status_code)), code


def request(method, path, payload=None, params=None, creds=None):
    """Authenticated JSON request. Raises RazorpayError with a sanitized message."""
    creds = creds or get_credentials()
    url = API_BASE + path.lstrip("/")
    try:
        resp = requests.request(
            method, url, json=payload, params=params, auth=(creds.key_id, creds.secret), timeout=TIMEOUT,
            headers={"Accept": "application/json", "User-Agent": "hospitality-core-razorpay/1.0"},
        )
    except requests.RequestException as e:
        raise RazorpayError(_("Could not reach Razorpay: {0}").format(type(e).__name__)) from None
    if resp.status_code >= 400:
        msg, code = _error_message(resp)
        raise RazorpayError(msg, resp.status_code, code)
    try:
        return resp.json()
    except ValueError:
        raise RazorpayError(_("Razorpay returned an unreadable response.")) from None


# ---- thin API wrappers -------------------------------------------------------------------------
def create_order(amount_paise, currency, receipt, notes, creds=None):
    return request("POST", "orders", {"amount": int(amount_paise), "currency": currency, "receipt": receipt[:40],
                                      "notes": notes}, creds=creds)


def fetch_order(order_id, creds=None):
    return request("GET", f"orders/{order_id}", creds=creds)


def fetch_order_payments(order_id, creds=None):
    return request("GET", f"orders/{order_id}/payments", creds=creds).get("items") or []


def fetch_payment(payment_id, creds=None):
    return request("GET", f"payments/{payment_id}", creds=creds)


def capture_payment(payment_id, amount_paise, currency, creds=None):
    return request("POST", f"payments/{payment_id}/capture", {"amount": int(amount_paise), "currency": currency}, creds=creds)


def create_refund(payment_id, amount_paise, notes, receipt, creds=None):
    return request("POST", f"payments/{payment_id}/refund",
                   {"amount": int(amount_paise), "notes": notes, "receipt": receipt[:40], "speed": "normal"}, creds=creds)


def fetch_refund(payment_id, refund_id, creds=None):
    return request("GET", f"payments/{payment_id}/refunds/{refund_id}", creds=creds)


def ping(creds=None):
    """Cheapest authenticated call: list one order."""
    return request("GET", "orders", params={"count": 1}, creds=creds)


def commit():
    """Commit at a safe boundary (after gateway state is known). Tests run inside one rolled-back
    transaction on a shared site, so commits are skipped there."""
    if not frappe.flags.in_test:
        frappe.db.commit()


def rollback_to(save_point):
    """Roll back to a savepoint; if an intermediate commit already released it, roll back the
    (uncommitted remainder of the) transaction instead. Never a full rollback inside tests."""
    try:
        frappe.db.rollback(save_point=save_point)
    except Exception:
        if not frappe.flags.in_test:
            frappe.db.rollback()


@contextmanager
def as_system_user():
    """Run server-controlled work (pricing, accounting documents) as Administrator for Guest / webhook /
    front-desk requests. Endpoints that lead here enforce their own access rules.

    frappe.set_user() rewrites session.sid, session.data and form_dict in place, so the switch is done
    on a copy of the session and the original objects are restored untouched afterwards."""
    local = frappe.local
    if local.session.user == "Administrator":
        yield
        return
    saved = (local.session, local.form_dict, getattr(local, "role_permissions", {}), getattr(local, "user_perms", None))
    local.session = frappe._dict(local.session)
    frappe.set_user("Administrator")
    try:
        yield
    finally:
        local.session, local.form_dict, local.role_permissions, local.user_perms = saved
        local.cache = {}
