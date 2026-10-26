"""PII scanning and redaction — regex-based, zero external ML dependencies.

Detects and redacts:
  - Email addresses
  - Phone numbers — US-style, and international ones written with a country code (`+49 151 2345 6789`,
    `0044 20 7946 0958`), 9 to 15 digits
  - Card numbers — written whole or in groups (`4111 1111 1111 1111`, `5500-0000-0000-0004`), a known card prefix
    and a passing Luhn check, so an ordinary long number is not taken for one
  - IBANs — written whole or in groups of four, kept only when their mod-97 check passes
  - Social Security Numbers
  - IPv4 addresses
  - Columns whose *names* suggest PII (email, phone, ssn, iban, password, token…)

The second, validated, set (2026-10-27): the redactor caught emails and US phones but let international numbers, grouped
card numbers and IBANs through — measured when mail and Google comments began arriving into the Record. Each new pattern
is checked (Luhn, mod 97, a digit count) before it redacts, because the same patterns scan query result cells, where a
false positive mangles real data.

Usage:
    result = PiiScanner.scan_and_redact(columns, rows)
    clean_rows = result.rows
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── Regex patterns ────────────────────────────────────────────────────────────

_RE_EMAIL = re.compile(
    r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'
)
# A US-style number; an area code in brackets is part of the match, so "(555) 123-4567" leaves no "(" behind.
_RE_PHONE = re.compile(
    r'(?<![\w(])(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b'
)
_RE_CC = re.compile(
    r'\b(?:'
    r'4[0-9]{12}(?:[0-9]{3})?'           # Visa
    r'|5[1-5][0-9]{14}'                   # MasterCard
    r'|3[47][0-9]{13}'                    # Amex
    r'|6(?:011|5[0-9]{2})[0-9]{12}'      # Discover
    r')\b'
)
_RE_SSN  = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
_RE_IPv4 = re.compile(
    r'\b(?:25[0-5]|2[0-4]\d|[01]?\d\d?)'
    r'\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)'
    r'\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)'
    r'\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b'
)

# A card written in groups: 13–19 digits with single spaces or dashes between them. Kept only with a known card prefix
# and a passing Luhn check (`_card_or_keep`).
_RE_CC_GROUPED = re.compile(r'\b\d{4}(?:[ -]\d{3,6}){2,4}\b')
_CARD_PREFIX = re.compile(r'^(?:4|5[1-5]|2(?:2[2-9]|[3-6]\d|7[01]|720)|3[47]|3(?:0[0-5]|[68])|35|6(?:011|5|4[4-9]))')
# An international phone: `+` or `00`, a 1–3 digit country code, then groups — 9 to 15 digits in all (`_phone_or_keep`).
_RE_PHONE_INTL = re.compile(r'(?<![\w+])(?:\+|00)\d{1,3}(?:[ .\-]?\(?\d{1,5}\)?){2,6}(?!\d)')
# An IBAN: two letters, two check digits, 11–30 letters or digits, written whole or in groups of four (`_iban_or_keep`).
_RE_IBAN = re.compile(r'\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b')


def _luhn(digits: str) -> bool:
    total, odd = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if odd:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        odd = not odd
    return total % 10 == 0


def _card_or_keep(m: re.Match) -> str:
    digits = re.sub(r'\D', '', m.group(0))
    if 13 <= len(digits) <= 19 and _CARD_PREFIX.match(digits) and _luhn(digits):
        return "[CARD]"
    return m.group(0)


def _phone_or_keep(m: re.Match) -> str:
    digits = re.sub(r'\D', '', m.group(0))
    if m.group(0).startswith("00"):
        digits = digits[2:]
    return "[PHONE]" if 9 <= len(digits) <= 15 else m.group(0)


def _iban_or_keep(m: re.Match) -> str:
    raw = m.group(0).replace(" ", "")
    if not 15 <= len(raw) <= 34:
        return m.group(0)
    moved = raw[4:] + raw[:4]
    number = "".join(str(int(ch, 36)) for ch in moved)
    return "[IBAN]" if int(number) % 97 == 1 else m.group(0)


# (pattern, replacement) — a label, or a function that redacts only what its check confirms. IBANs before cards and
# phones, whose digit runs they contain; validated grouped cards before the international phone pattern.
_PATTERNS: list[tuple[re.Pattern[str], object]] = [
    (_RE_EMAIL,  "[EMAIL]"),
    (_RE_IBAN,   _iban_or_keep),
    (_RE_CC,     "[CARD]"),
    (_RE_CC_GROUPED, _card_or_keep),
    (_RE_SSN,    "[SSN]"),
    (_RE_PHONE_INTL, _phone_or_keep),
    (_RE_PHONE,  "[PHONE]"),
    (_RE_IPv4,   "[IP]"),
]

# A cell that is a single decimal / scientific-notation number is a measurement
# or aggregate, never PII. Credit-card / SSN / phone numbers are integers with no
# decimal point, so a value like "3.4012888888881881" (a SUM with a long
# fractional part) must NOT be scanned — otherwise its fractional digits get
# mangled into "[CARD]". Plain integers are deliberately still scanned so a bare
# 16-digit card number in an un-named column is still caught.
_NUMERIC_DECIMAL_RE = re.compile(
    r'^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)?\.\d+(?:[eE][+-]?\d+)?$'  # has a decimal point
    r'|^[+-]?\d+[eE][+-]?\d+$'                                    # or scientific notation
)


def _is_decimal_number(val: str) -> bool:
    """True if the whole cell is one decimal/scientific number (so not PII)."""
    return bool(_NUMERIC_DECIMAL_RE.match(val.strip()))


# Column name patterns whose values should always be redacted
_PII_COL_RE = re.compile(
    r'\b(?:email|phone|mobile|cell_?phone|ssn|sin|'
    r'credit_?card|card_?number|card_?no|cvv|iban|'
    r'ip_?addr(?:ess)?|password|passwd|pwd|'
    r'api_?(?:key|token|secret)|auth_?token|'
    r'secret|private_?key)\b',
    re.I,
)


@dataclass
class PiiScanResult:
    rows: list[list[str]]
    redacted_count: int
    pii_columns: list[str] = field(default_factory=list)


class PiiScanner:
    """Stateless PII scanner. All methods are class-level."""

    @classmethod
    def scan_and_redact(
        cls,
        columns: list[str],
        rows: list[list[str]],
    ) -> PiiScanResult:
        """
        Scan rows for PII and return redacted copies.

        Two-pass strategy:
          1. Column name heuristic — cells in PII-named columns are always redacted.
          2. Value pattern scan — all other cells checked against regex patterns.
        """
        if not rows:
            return PiiScanResult(rows=rows, redacted_count=0, pii_columns=[])

        # Identify PII-named column indices
        pii_indices: set[int] = set()
        pii_col_names: list[str] = []
        for i, col in enumerate(columns):
            if _PII_COL_RE.search(col):
                pii_indices.add(i)
                pii_col_names.append(col)

        redacted_count = 0
        new_rows: list[list[str]] = []

        for row in rows:
            new_row = list(row)
            for i, val in enumerate(new_row):
                if not isinstance(val, str) or val in ("NULL", "None", ""):
                    continue

                # Column-name based: always redact entire cell
                if i in pii_indices:
                    if val not in ("[REDACTED]",):
                        new_row[i] = "[REDACTED]"
                        redacted_count += 1
                    continue

                # A standalone decimal/scientific number is an aggregate or
                # measurement, never PII — skip it so long fractional digit runs
                # aren't misread as a credit-card number ("3.40128…" → "3.[CARD]").
                if _is_decimal_number(val):
                    continue

                # Pattern-based: replace within cell (may be partial match)
                original = val
                for pattern, label in _PATTERNS:
                    val = pattern.sub(label, val)
                if val != original:
                    new_row[i] = val
                    redacted_count += 1

            new_rows.append(new_row)

        return PiiScanResult(
            rows=new_rows,
            redacted_count=redacted_count,
            pii_columns=pii_col_names,
        )

    @classmethod
    def has_pii(cls, columns: list[str], rows: list[list[str]]) -> bool:
        """Quick check — returns True if any PII was detected (without redacting)."""
        result = cls.scan_and_redact(columns, rows)
        return result.redacted_count > 0


def redact_text(text: str) -> str:
    """Free-text redaction over the same patterns the row scanner uses — HB-5's intake
    customs (an arrival sentence is scrubbed before it is stored as a note). The
    decimal-number guard is a CELL rule and deliberately does not apply to prose:
    a sentence is never one bare aggregate."""
    out = text or ""
    for pattern, label in _PATTERNS:
        out = pattern.sub(label, out)
    return out
