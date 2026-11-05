"""Bilingual (Hindi / English) payment-reminder messages and the free ways to deliver them.

Free delivery that needs no SMS provider and no DLT registration:
  * a WhatsApp click-to-chat link (wa.me) with the message pre-filled, and
  * an sms: link that opens the shopkeeper's own phone SMS app with the message pre-filled.
The shopkeeper taps Send, so it is sent from their own number/SIM at their own plan's rate.

Fully automatic SMS goes through apps.web.sms (needs a provider + TRAI DLT registration).
"""
import re
from urllib.parse import quote

LANGS = [("en", "English"), ("hi", "हिन्दी (Hindi)"), ("both", "Hindi + English")]

# Wording kept short: Hindi text is Unicode, so one SMS part holds only 70 characters.
EN = "Dear {name}, you owe Rs {amount} at {shop}. Please pay as soon as possible. Thank you. - LenDen Saathi"
HI = "प्रिय {name}, {shop} में आपका Rs {amount} बकाया है। कृपया जल्द से जल्द भुगतान करें। धन्यवाद। - LenDen Saathi"


def normalize_mobile(raw: str) -> str | None:
    """Return a 10-digit Indian mobile number (starts 6-9) or None. Accepts +91, 91, 0 prefixes, spaces and dashes."""
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return d if re.fullmatch(r"[6-9]\d{9}", d) else None


def rupees_text(paise: int) -> str:
    """Whole rupees, or rupees with paise, Indian digit grouping, no symbol: 150050 -> '1,500.50'."""
    r, p = divmod(max(int(paise), 0), 100)
    s = str(r)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return s if p == 0 else f"{s}.{p:02d}"


def _clean(text: str, limit: int) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def build_message(lang: str, customer: str, shop: str, balance_paise: int) -> str:
    """The reminder text. lang is 'en', 'hi' or 'both' (Hindi first, then English)."""
    vals = {"name": _clean(customer, 40) or "Customer", "shop": _clean(shop, 40) or "our shop", "amount": rupees_text(balance_paise)}
    if lang == "hi":
        return HI.format(**vals)
    if lang == "both":
        return HI.format(**vals) + "\n" + EN.format(**vals)
    return EN.format(**vals)


def whatsapp_link(mobile10: str, text: str) -> str:
    return f"https://wa.me/91{mobile10}?text={quote(text)}"


def sms_link(mobile10: str, text: str) -> str:
    return f"sms:+91{mobile10}?body={quote(text)}"
