"""VA-1 — the gate every imported skill passes before it can become a pack.

A skill is **third-party prose that will be pasted into a model's context**. That is the
whole threat model: it is not code we review, it is instructions we adopt, and the model
cannot tell the difference between a skill's sentence and ours.

The import scope chosen for this wave is "all data/analytics skills, spot-checked", which
promotes this file from a backstop to **the primary line of defence** — most skills will
be read by a linter and sampled by a human, not read by a human one at a time. So the
severity split does real work:

- ``BLOCK`` is for what no legitimate data skill needs: a phrase whose only function is to
  countermand instructions, a credential with real entropy, a hardcoded model id.
- ``WARN`` is for what a legitimate skill *often* does and a reviewer should still see —
  the word "password" inside a connection-string example, an outbound URL. Warnings are
  the spot-check's worklist, not a verdict.

Being explicit about the limit: a text linter cannot decide intent, and a sufficiently
polite instruction to do the wrong thing will read as ordinary prose. This gate raises the
cost of a hostile skill and makes the questionable ones visible; it does not make importing
arbitrary text safe, and nothing here should be described as if it did.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    BLOCK = "block"
    WARN = "warn"


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: Severity
    line: int
    excerpt: str
    why: str


def _lines(text: str) -> list[str]:
    return text.splitlines()


# ── 1 · model ids ────────────────────────────────────────────────────────────────
# This repo forbids its own source from naming a model (a hardcoded id is an assertion
# about another vendor's catalogue that we have no way to keep true, and the picker reads
# the provider's /models instead). A skill that pins one smuggles that assertion back in
# through prose, and it will outlive the model.
_MODEL_ID = re.compile(
    r"\b("
    r"gpt-[0-9][\w.\-]*"
    r"|o[1-9](?:-[\w.]+)?\b"
    r"|claude-[0-9][\w.\-]*|claude-(?:opus|sonnet|haiku)-[\w.\-]*"
    r"|gemini-[0-9][\w.\-]*"
    r"|llama-?[0-9][\w.\-]*"
    r"|mistral-(?:large|small|medium)[\w.\-]*"
    r"|deepseek-[\w.\-]+"
    r"|qwen[0-9][\w.\-]*"
    r")\b",
    re.I,
)

# ── 2 · credentials ──────────────────────────────────────────────────────────────
# The patterns and the entropy judgement live in `aughor/security/credentials.py`, not
# here: VA-5's trace-payload inspector needs exactly the same call — is this a real key or
# a documentation placeholder — and two copies of that judgement drift into two different
# answers for the same string. This module keeps the POLICY (what a skill may carry);
# the security module owns the DETECTION.
from aughor.security.credentials import (  # noqa: E402
    KEY_SHAPES as _KEY_SHAPES,
    PLACEHOLDER as _PLACEHOLDER,
    SECRET_ASSIGN as _SECRET_ASSIGN,
    entropy as _entropy,
    MIN_SECRET_LEN as _MIN_SECRET_LEN,
    SECRET_ENTROPY as _SECRET_ENTROPY,
)


# ── 3 · instruction injection ────────────────────────────────────────────────────
# Phrases whose only function is to countermand the instructions already in context. A
# data skill teaching ClickHouse joins never needs one of these.
_INJECTION = [
    (re.compile(r"(?i)\bignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+"
                r"(instruction|prompt|rule|direction)"), "countermands prior instructions"),
    (re.compile(r"(?i)\bdisregard\s+(your|all|any|the)\s+"
                r"(instruction|rule|guard|guideline|constraint|safety)"),
     "asks the model to drop its rules"),
    (re.compile(r"(?i)\b(bypass|circumvent|override|disable|turn off)\s+"
                r"(the\s+|your\s+|all\s+)?(guard|guardrail|safety|check|validation|filter)"),
     "asks the model to disable a guard"),
    (re.compile(r"(?i)\b(reveal|print|output|repeat|show)\s+(your|the)\s+"
                r"(system\s+prompt|instructions|initial\s+prompt)"),
     "attempts to extract the system prompt"),
    (re.compile(r"(?i)\byou\s+are\s+now\s+(a|an|no longer)\b"),
     "attempts to replace the assistant's identity"),
    (re.compile(r"(?i)\bdo\s+not\s+(tell|inform|mention to|reveal to)\s+the\s+user\b"),
     "asks the model to conceal something from the user"),
    (re.compile(r"(?i)\bwithout\s+(asking|telling|informing)\s+(the\s+)?(user|human)\b"),
     "asks the model to act without the user's knowledge"),
]

# ── 4 · exfiltration ─────────────────────────────────────────────────────────────
_EXFIL = re.compile(
    r"(?i)\b(send|post|upload|forward|exfiltrate|transmit)\b[^.\n]{0,60}"
    r"\b(to|at)\b\s*(https?://|www\.)")

_URL = re.compile(r"https?://[^\s)\"'<>]+")

#: A skill is prompt content and prompt content has a token cost. Past this, a reviewer
#: should be asked whether it earns its place — measured discipline from the PE waves.
_LARGE_SKILL_CHARS = 20_000


def lint_skill(text: str, *, name: str = "") -> list[Finding]:
    """Every rule, over one skill's markdown. Ordered by line for a readable report."""
    out: list[Finding] = []

    for i, line in enumerate(_lines(text), start=1):
        for m in _MODEL_ID.finditer(line):
            out.append(Finding(
                "model-id", Severity.BLOCK, i, m.group(0),
                "names a specific model. This repo forbids hardcoded model ids in its own "
                "source; a skill that pins one asserts a fact about a vendor catalogue we "
                "cannot keep true, and it will outlive the model."))

        for m in _KEY_SHAPES.finditer(line):
            out.append(Finding(
                "credential", Severity.BLOCK, i, m.group(0)[:12] + "…",
                "looks like a real credential (recognised key prefix). A skill is public "
                "prose; a key in one is already compromised."))

        for m in _SECRET_ASSIGN.finditer(line):
            value = m.group(2)
            if _PLACEHOLDER.match(value):
                continue
            if _entropy(value) >= _SECRET_ENTROPY and len(value) >= _MIN_SECRET_LEN:
                out.append(Finding(
                    "credential", Severity.BLOCK, i, f"{m.group(1)}=…",
                    "assigns a high-entropy literal to a secret-shaped name. A placeholder "
                    "would read as one; this does not."))
            else:
                out.append(Finding(
                    "secret-shaped", Severity.WARN, i, f"{m.group(1)}=…",
                    "mentions a secret by name. Usually a connection-string example — "
                    "worth a human glance, not a refusal."))

        for pattern, why in _INJECTION:
            m = pattern.search(line)
            if m:
                out.append(Finding("injection", Severity.BLOCK, i, m.group(0), why))

        if _EXFIL.search(line):
            out.append(Finding(
                "exfiltration", Severity.BLOCK, i, _EXFIL.search(line).group(0)[:60],
                "instructs the agent to send data to an external address."))

        for m in _URL.finditer(line):
            out.append(Finding(
                "external-url", Severity.WARN, i, m.group(0)[:60],
                "links outward. Fine for documentation; a reviewer should confirm the "
                "skill does not instruct the agent to fetch from it."))

    if len(text) > _LARGE_SKILL_CHARS:
        out.append(Finding(
            "size", Severity.WARN, 1, f"{len(text):,} chars",
            f"is larger than {_LARGE_SKILL_CHARS:,} characters. Skills are prompt content "
            f"and prompt content has a token cost — confirm it earns its place."))

    return sorted(out, key=lambda f: (f.line, f.rule))


def blocks(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity is Severity.BLOCK]


def is_importable(findings: list[Finding]) -> bool:
    """True when nothing BLOCKS. Warnings are the spot-check's worklist, not a verdict."""
    return not blocks(findings)
