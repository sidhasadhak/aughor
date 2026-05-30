"""SQL safety checker — classifies queries as SAFE, SUSPICIOUS, or BLOCKED.

No external dependencies. Uses token matching + scored regex patterns.

Scoring rules:
  - First token in BLOCKED_TOKENS  → immediately BLOCKED  (score 1.0)
  - BLOCKED token anywhere in body → +0.5 per hit
  - _SUSPICIOUS_PATTERNS match     → add pattern weight
  - score >= BLOCKED_THRESHOLD     → BLOCKED
  - score >  0                     → SUSPICIOUS
  - else                           → SAFE
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class SafetyVerdict(str, Enum):
    SAFE       = "safe"
    SUSPICIOUS = "suspicious"
    BLOCKED    = "blocked"


@dataclass(frozen=True)
class SafetyResult:
    verdict: SafetyVerdict
    reason: str
    score: float  # 0.0–1.0; contextual, not a probability


# ── Token lists ───────────────────────────────────────────────────────────────

# These as the *first* SQL token always block execution
_FIRST_BLOCKED: frozenset[str] = frozenset({
    "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE",
    "CREATE", "ALTER", "REPLACE", "UPSERT", "MERGE",
    "GRANT", "REVOKE", "EXECUTE", "EXEC", "CALL", "COPY",
})

# These anywhere in the statement raise the score
_BODY_RISKY: frozenset[str] = frozenset({
    "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE",
    "CREATE", "ALTER", "GRANT", "REVOKE", "EXECUTE",
})

# ── Suspicious pattern rules (pattern, score_weight, label) ──────────────────

_RULES: list[tuple[re.Pattern[str], float, str]] = [
    # Credential / shadow tables
    (re.compile(r'\bpg_shadow\b|\bpg_authid\b|\bpg_user\b', re.I),   0.9, "credential table access"),
    # System catalog (informational, not necessarily bad)
    (re.compile(r'\bpg_catalog\b|\binformation_schema\b', re.I),      0.3, "system catalog access"),
    # Stacked queries  (e.g.  ; DROP TABLE --)
    (re.compile(r';\s*(?:SELECT|INSERT|UPDATE|DELETE|DROP)', re.I),   0.9, "stacked queries"),
    # Time-delay injection
    (re.compile(r'\bpg_sleep\s*\(|\bsleep\s*\(|\bWAITFOR\s+DELAY', re.I), 1.0, "time-delay injection"),
    # Credentials in comments
    (re.compile(r'--.*(?:password|secret|api_key|token)', re.I),      0.5, "credential hint in comment"),
    # UNION-based injection hint
    (re.compile(r'UNION\s+(?:ALL\s+)?SELECT', re.I),                  0.4, "UNION SELECT (possible injection)"),
    # Very large LIMIT  (>100k rows — probably an accident)
    (re.compile(r'LIMIT\s+(?:[1-9]\d{5,})', re.I),                   0.3, "excessively large LIMIT"),
    # Hex literals (obfuscation attempt)
    (re.compile(r'\b0x[0-9a-fA-F]{8,}\b'),                           0.4, "hex literal obfuscation"),
    # xp_cmdshell / OS execution  (MSSQL-style)
    (re.compile(r'\bxp_cmdshell\b|\bsp_execute\b', re.I),            1.0, "OS execution attempt"),
    # Comment stripping tricks  (/**/ style)
    (re.compile(r'/\*[^*]*\*+(?:[^/*][^*]*\*+)*/'),                  0.2, "inline comment (obfuscation risk)"),
]

_BLOCKED_THRESHOLD = 0.8


def _strip_comments(sql: str) -> str:
    sql = re.sub(r'--[^\n]*', '', sql)
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    return sql


class SafetyChecker:
    """Stateless SQL safety checker. All methods are class-level."""

    @classmethod
    def check(cls, sql: str) -> SafetyResult:
        """Return a SafetyResult for the given SQL string."""
        clean = _strip_comments(sql).strip()

        # First token check — hard block on write/DDL
        tokens = re.findall(r'[A-Za-z_][A-Za-z0-9_]*', clean)
        first = tokens[0].upper() if tokens else ""
        if first in _FIRST_BLOCKED:
            return SafetyResult(
                verdict=SafetyVerdict.BLOCKED,
                reason=f"{first} statements are not permitted in read-only mode",
                score=1.0,
            )

        # Score: body risky tokens
        score = 0.0
        reasons: list[str] = []
        for token in _BODY_RISKY:
            if re.search(rf'\b{token}\b', clean, re.I):
                score = min(1.0, score + 0.5)
                reasons.append(f"{token} in statement body")

        # Score: pattern rules (run on original SQL, not stripped)
        for pattern, weight, label in _RULES:
            if pattern.search(sql):
                score = min(1.0, score + weight)
                reasons.append(label)

        if score >= _BLOCKED_THRESHOLD:
            return SafetyResult(
                verdict=SafetyVerdict.BLOCKED,
                reason="; ".join(reasons) or "high-risk pattern detected",
                score=score,
            )
        if score > 0.0:
            return SafetyResult(
                verdict=SafetyVerdict.SUSPICIOUS,
                reason="; ".join(reasons),
                score=score,
            )
        return SafetyResult(verdict=SafetyVerdict.SAFE, reason="", score=0.0)

    @classmethod
    def is_allowed(cls, sql: str) -> tuple[bool, str]:
        """Convenience wrapper — returns (True, '') or (False, reason)."""
        result = cls.check(sql)
        if result.verdict == SafetyVerdict.BLOCKED:
            return False, result.reason
        return True, result.reason  # reason may be non-empty for SUSPICIOUS
