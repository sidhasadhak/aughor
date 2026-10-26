"""The PII redactor's second, validated set (2026-10-27; `aughor/security/pii.py`).

Measured when mail and Google comments began arriving into the Record: the redactor caught emails and US phones and let
international numbers, grouped card numbers and IBANs through. What these hold: each of those is redacted in prose and
in a result cell; each new pattern redacts only what its check confirms — a card's prefix and Luhn, an IBAN's mod 97, a
phone's digit count — so an ordinary long number, a date, a growth figure or an aggregate is left as it was; and a US
number in brackets leaves nothing of itself behind.
"""
from __future__ import annotations

import pytest

from aughor.security.pii import PiiScanner, redact_text


@pytest.mark.parametrize("said, kept", [
    ("call +49 151 2345 6789 today", "call [PHONE] today"),
    ("or 0044 20 7946 0958", "or [PHONE]"),
    ("India +91 98765 43210", "India [PHONE]"),
    ("UK +44 (20) 7946 0958.", "UK [PHONE]."),
    ("card 4111 1111 1111 1111", "card [CARD]"),
    ("mc 5500-0000-0000-0004", "mc [CARD]"),
    ("amex 3782 822463 10005", "amex [CARD]"),
    ("IBAN DE89 3704 0044 0532 0130 00", "IBAN [IBAN]"),
    ("iban GB82WEST12345698765432 for the refund", "iban [IBAN] for the refund"),
    ("phone (555) 123-4567", "phone [PHONE]"),
    ("write to carla@agency.example", "write to [EMAIL]"),
])
def test_what_identifies_a_person_or_an_account_is_redacted(said, kept):
    assert redact_text(said) == kept


@pytest.mark.parametrize("plain", [
    "not a card 1234 5678 9012 3456",                 # no card prefix, fails Luhn
    "4111 1111 1111 1112",                            # a card prefix, but fails Luhn
    "bad iban DE89370400440532013001",                # the IBAN's mod-97 check fails
    "revenue rose +12 345 678 EUR",                   # a signed figure, too few digits for a phone
    "the week of 2026-10-12 to 2026-10-18",
    "ratio 3.40128888888818",
    "+3.2% growth on 158,815 EUR",
    "order 12345678 shipped",
])
def test_an_ordinary_number_is_left_as_it_was(plain):
    assert redact_text(plain) == plain


def test_a_result_cell_is_redacted_by_the_same_checks_and_an_aggregate_is_not():
    out = PiiScanner.scan_and_redact(
        ["note", "amount", "account"],
        [["refund to DE89 3704 0044 0532 0130 00", "3.40128888888818", "acct 1"],
         ["call +49 151 2345 6789", "158815.76", "acct 2"]])
    assert out.rows[0][0] == "refund to [IBAN]" and out.rows[1][0] == "call [PHONE]"
    assert out.rows[0][1] == "3.40128888888818" and out.rows[1][1] == "158815.76"
    assert out.redacted_count == 2


def test_a_column_named_iban_is_redacted_whole():
    out = PiiScanner.scan_and_redact(["iban"], [["anything at all"]])
    assert out.rows[0][0] == "[REDACTED]" and out.pii_columns == ["iban"]
