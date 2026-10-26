"""Standardise individual values (no business decisions here)."""
from __future__ import annotations


def clean_text(value):
    """Trim and collapse internal whitespace; blank becomes None."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def normalise_email(value):
    text = clean_text(value)
    return text.lower() if text else None


def is_valid_email(email, rules):
    return bool(email) and rules.email_re.fullmatch(email) is not None


def normalise_source_system(value):
    text = clean_text(value)
    return text.lower() if text else None


def normalise_domain(value):
    text = clean_text(value)
    if not text:
        return None
    text = text.lower().rstrip(".")
    if text.startswith("www."):
        text = text[4:]
    return text or None


def normalise_country(value, rules):
    """Return (code, status). Status: supported, unsupported, missing or unrecognised.

    Countries are never inferred from language, email domain or IP (LF-002).
    """
    text = clean_text(value)
    if not text:
        return None, "missing"
    code = rules.country_aliases.get(text.casefold())
    if code is None:
        return None, "unrecognised"
    return code, ("supported" if code in rules.supported_countries else "unsupported")
