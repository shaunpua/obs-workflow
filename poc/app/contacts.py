"""Pull contact details and links out of message text. Pure functions, no I/O.

Messenger never hands us a guest's phone or email, so guests who type one into the chat are the only source
(`messaging_customer_information` / lead-form payloads, if they ever arrive, would be a second source).
"""
from __future__ import annotations

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
# A run of digits with the usual separators between them: "0917 123 4567", "+63 917-123-4567", "(02) 8123 4567".
# Commas are deliberately NOT separators, so prices ("1,500,000") and dates ("2026-10-05", "Oct 18-19") don't match.
_PHONE = re.compile(r"(?<![\w.])\+?\(?\d[\d\s().\-]{6,}\d(?![\w])")
_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


def extract_emails(text: str | None) -> list[str]:
    seen: list[str] = []
    for m in _EMAIL.findall(text or ""):
        e = m.rstrip(".").lower()
        if e not in seen:
            seen.append(e)
    return seen


def extract_phones(text: str | None) -> list[str]:
    """Phone numbers as '+' (if typed) followed by digits only. 10-15 digits; shorter runs are ignored as dates/prices."""
    text = _EMAIL.sub(" ", text or "")          # digits inside an email address aren't a phone number
    out: list[str] = []
    for m in _PHONE.finditer(text):
        raw = m.group(0).strip()
        digits = re.sub(r"\D", "", raw)
        if not 10 <= len(digits) <= 15:
            continue
        num = ("+" if raw.lstrip("(").startswith("+") else "") + digits
        if num not in out:
            out.append(num)
    return out


def extract_urls(text: str | None) -> list[str]:
    out: list[str] = []
    for u in _URL.findall(text or ""):
        u = u.rstrip(".,;:!?")
        if u not in out:
            out.append(u)
    return out
