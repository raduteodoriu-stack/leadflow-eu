"""Unit tests: value standardisation (LF-006)."""
import pytest

from leadflow import load_rules
from leadflow.normalise import (clean_text, is_valid_email, normalise_country, normalise_domain,
                                normalise_email, normalise_source_system)

RULES = load_rules()


@pytest.mark.parametrize("raw, expected", [
    ("Ana.Garcia@Synthetic-Research.example ", "ana.garcia@synthetic-research.example"),
    ("  MARTA.Lopez@Agencia.example", "marta.lopez@agencia.example"),
    ("", None), (None, None),
])
def test_email_is_trimmed_and_lower_cased(raw, expected):
    assert normalise_email(raw) == expected


@pytest.mark.parametrize("email, valid", [
    ("ana.garcia@synthetic-research.example", True),
    ("o'neil+leads@mail.example", True),
    ("lucia.ortega(at)estudios-ok.example", False),
    ("first.last@", False),
    ("@synthetic.example", False),
    ("abc", False),
    (None, False),
])
def test_email_format(email, valid):
    assert is_valid_email(email, RULES) is valid


@pytest.mark.parametrize("raw, code, status", [
    ("España", "ES", "supported"), (" Spain ", "ES", "supported"), ("es", "ES", "supported"),
    ("portugal", "PT", "supported"), ("France", "FR", "supported"),
    ("Deutschland", "DE", "unsupported"), ("United Kingdom", "GB", "unsupported"),
    ("Atlantis", None, "unrecognised"), ("", None, "missing"), ("   ", None, "missing"), (None, None, "missing"),
])
def test_country_aliases(raw, code, status):
    assert normalise_country(raw, RULES) == (code, status)


def test_domain_and_text_cleaning():
    assert normalise_domain(" WWW.Panel-Delta.example. ") == "panel-delta.example"
    assert normalise_domain("") is None
    assert clean_text("  two   spaces ") == "two spaces"
    assert normalise_source_system(" HubSpot ") == "hubspot"
