"""Automatic SMS to Indian mobile numbers, behind one small interface.

Nothing here is switched on by default. In India every commercial SMS must use a TRAI DLT-registered sender ID and a
pre-approved template, so a provider account is needed first. Set in the environment:

    SMS_PROVIDER=fast2sms            # or leave empty to keep automatic SMS off
    FAST2SMS_API_KEY=...             # from the Fast2SMS dashboard
    FAST2SMS_SENDER_ID=...           # your 6-character DLT header
    FAST2SMS_TEMPLATE_EN=...         # DLT template (message) IDs for the three approved templates
    FAST2SMS_TEMPLATE_HI=...
    FAST2SMS_TEMPLATE_BOTH=...

The template bodies to register are in DLT_TEMPLATES below, with {#var#} as the three variables (name, shop, amount).
Until a provider is configured, reminders are still logged and can be sent for free by WhatsApp or the phone's SMS app.
"""
import logging

import requests
from django.conf import settings

from . import reminders

log = logging.getLogger("web.sms")

# Register these exact texts on the DLT portal (variables in this order: name | shop | amount).
DLT_TEMPLATES = {
    "en": "Dear {#var#}, you owe Rs {#var#} at {#var#}. Please pay as soon as possible. Thank you. - UdhaarSaathi",
    "hi": "प्रिय {#var#}, {#var#} में आपका Rs {#var#} बकाया है। कृपया जल्द से जल्द भुगतान करें। धन्यवाद। - UdhaarSaathi",
}
# Note: the variable order above is name, shop, amount for Hindi and name, amount, shop for English; send() orders them per language.


class SmsError(Exception):
    pass


def provider() -> str:
    return (getattr(settings, "SMS_PROVIDER", "") or "").strip().lower()


def configured() -> bool:
    return provider() == "fast2sms" and bool(getattr(settings, "FAST2SMS_API_KEY", "")) and bool(getattr(settings, "FAST2SMS_SENDER_ID", ""))


def _variables(lang: str, name: str, shop: str, amount: str) -> str:
    name, shop = reminders._clean(name, 30).replace("|", " "), reminders._clean(shop, 30).replace("|", " ")
    return "|".join([name, shop, amount] if lang == "hi" else [name, amount, shop])


def send(mobile10: str, lang: str, customer: str, shop: str, balance_paise: int) -> str:
    """Send one reminder. lang 'both' sends the Hindi and the English SMS as two messages. Returns a short provider reference.
    Raises SmsError on any failure so the caller can log it and fall back to the free links."""
    if not configured():
        raise SmsError("Automatic SMS is not set up (no provider / DLT details).")
    if not reminders.normalize_mobile(mobile10):
        raise SmsError("Not a valid Indian mobile number.")
    refs = []
    for one in (["hi", "en"] if lang == "both" else [lang if lang in ("hi", "en") else "en"]):
        template = getattr(settings, f"FAST2SMS_TEMPLATE_{one.upper()}", "")
        if not template:
            raise SmsError(f"No DLT template id configured for '{one}'.")
        try:
            r = requests.post(
                "https://www.fast2sms.com/dev/bulkV2",
                headers={"authorization": settings.FAST2SMS_API_KEY},
                data={"route": "dlt", "sender_id": settings.FAST2SMS_SENDER_ID, "message": template,
                      "variables_values": _variables(one, customer, shop, reminders.rupees_text(balance_paise)),
                      "flash": 0, "numbers": mobile10},
                timeout=20)
            body = r.json()
        except (requests.RequestException, ValueError) as e:
            raise SmsError(f"SMS provider unreachable: {type(e).__name__}") from e
        if r.status_code != 200 or not body.get("return"):
            log.warning("fast2sms refused: %s", str(body)[:200])
            raise SmsError(str(body.get("message", "SMS provider refused the message"))[:160])
        refs.append(str(body.get("request_id", "")))
    return ",".join(refs)
