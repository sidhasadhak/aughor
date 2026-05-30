"""PII scanning and redaction — regex-based, zero external ML dependencies.

Detects and redacts:
  - Email addresses
  - Phone numbers (US/international)
  - Credit card numbers (Visa, MC, Amex, Discover)
  - Social Security Numbers
  - IPv4 addresses
  - Columns whose *names* suggest PII (email, phone, ssn, password, token…)

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
_RE_PHONE = re.compile(
    r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'
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

# (pattern, replacement_label)
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (_RE_EMAIL,  "[EMAIL]"),
    (_RE_CC,     "[CARD]"),
    (_RE_SSN,    "[SSN]"),
    (_RE_PHONE,  "[PHONE]"),
    (_RE_IPv4,   "[IP]"),
]

# Column name patterns whose values should always be redacted
_PII_COL_RE = re.compile(
    r'\b(?:email|phone|mobile|cell_?phone|ssn|sin|'
    r'credit_?card|card_?number|card_?no|cvv|'
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
