"""Credential detection and masking over free text — one detector, several consumers.

Two surfaces need the same judgement and would otherwise grow their own copies:

* **Skill ingestion** (VA-1) refuses third-party prose carrying a real key.
* **Trace payloads** (VA-5) render captured prompts, generated SQL and tool output to
  an operator. A credential that reaches a payload is already somewhere it should not
  be, and a trace viewer then puts it on a screen, in a browser cache, and in whatever
  the reader pastes into a bug report.

The judgement is the same in both places — *is this a real secret or a documentation
placeholder* — so it lives in one place. `password=hunter2` in a tutorial is
documentation; `password=<40 random chars>` is a leak; a rule that cannot tell them
apart trains people to ignore it. Prefixed key shapes are unambiguous on sight;
everything else is decided by entropy and length.

**Masking is not PII redaction, and deliberately not.** Arc VA's decision ③
is that admins see everything on a trace, audited — so the operator's own data, questions
and SQL are theirs to read. A credential is the exception because it is not the subject's
data at all: it is an access token that reading grants, which is why it is masked for
every reader rather than gated by role.
"""
from __future__ import annotations

import math
import re
from collections import Counter

# Prefixed key shapes. Unambiguous — no entropy test needed, the vendor prefix IS the tell.
KEY_SHAPES = re.compile(
    r"\b("
    r"sk-[A-Za-z0-9_\-]{16,}"
    r"|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{12,}"
    r"|xox[baprs]-[A-Za-z0-9\-]{10,}"
    r"|AIza[0-9A-Za-z_\-]{30,}"
    r"|eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}"
    r")\b"
)
SECRET_ASSIGN = re.compile(
    r"(?i)\b(api[_\-]?key|secret|token|password|passwd|pwd|bearer)\b\s*[:=]\s*"
    # 3+, not 12+: `password: mypass` is short AND worth a reviewer's glance. Length and
    # entropy decide BLOCK vs WARN; they must not decide whether we LOOK at all.
    r"[\"']?([A-Za-z0-9/+_\-\.]{3,})[\"']?"
)
#: Obvious placeholders are documentation, not leaks.
PLACEHOLDER = re.compile(
    r"(?i)^(your|my|the)?[_\-]?(api[_\-]?key|secret|token|password|value|xxx+|placeholder|"
    r"changeme|example|redacted|dummy|test|fake|<[^>]+>|\$\{?[a-z_]+\}?|hunter2)$"
)

#: Above this, a secret-shaped assignment's value is judged a real secret rather than a
#: placeholder — provided it is also at least :data:`MIN_SECRET_LEN` long.
SECRET_ENTROPY = 3.2
MIN_SECRET_LEN = 16

MASK = "[CREDENTIAL REDACTED]"


def entropy(s: str) -> float:
    """Shannon entropy in bits per character. `hunter2` scores low, 40 random chars high."""
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def looks_like_secret(value: str) -> bool:
    """True when a secret-shaped assignment's VALUE reads as a real credential.

    Deliberately conservative in the direction that matters here: a placeholder wrongly
    masked costs a reader nothing, and a real key wrongly shown is unrecoverable.
    """
    if not value or PLACEHOLDER.match(value):
        return False
    return len(value) >= MIN_SECRET_LEN and entropy(value) >= SECRET_ENTROPY


def mask_credentials(text: str) -> tuple[str, int]:
    """``(masked_text, count)``. Non-destructive to everything that is not a credential.

    Only the VALUE of a secret-shaped assignment is replaced, never the key name — a
    reader still needs to see that a password was set, and where, in order to go and
    rotate it. Showing ``password=[CREDENTIAL REDACTED]`` says both things; dropping the
    line says neither.
    """
    if not text:
        return text, 0
    count = 0

    def _key(m: re.Match) -> str:
        nonlocal count
        count += 1
        return MASK

    out = KEY_SHAPES.sub(_key, text)

    def _assign(m: re.Match) -> str:
        nonlocal count
        if not looks_like_secret(m.group(2)):
            return m.group(0)
        count += 1
        return m.group(0).replace(m.group(2), MASK)

    out = SECRET_ASSIGN.sub(_assign, out)
    return out, count


def mask_payload(value, _depth: int = 0):
    """:func:`mask_credentials` over a nested JSON-ish structure — ``(value, count)``.

    Depth-bounded because a trace payload is arbitrary data from the run, not a shape we
    control, and a masker that can be made to recurse forever by the thing it inspects is
    a denial of service wearing a safety feature.
    """
    if _depth > 12:
        return value, 0
    if isinstance(value, str):
        return mask_credentials(value)
    if isinstance(value, dict):
        total = 0
        out = {}
        for k, v in value.items():
            out[k], n = mask_payload(v, _depth + 1)
            total += n
        return out, total
    if isinstance(value, (list, tuple)):
        total = 0
        items = []
        for v in value:
            masked, n = mask_payload(v, _depth + 1)
            items.append(masked)
            total += n
        return (items if isinstance(value, list) else tuple(items)), total
    return value, 0
