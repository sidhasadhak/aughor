"""Wave G6 — say, on the answer, what governance did to produce it.

Two facts exist somewhere in the platform and neither reaches the person reading an
answer:

1. **Which standing grants applied.** ``govern.actions`` keeps an action allowlist, and a
   HIGH-risk action covered by one is auto-approved silently. J2's rule is that a standing
   grant is a *standing* decision, so it must stay visible and revocable — a grant nobody
   can see is a grant nobody will ever revoke.
2. **Which identity the query ran as.** Every connection executes under some credential,
   and today the answer never says whose. "Why can I see this?" and "why can't I?" both
   have the same root cause and neither is answerable from the UI.
**The redaction rule, which is the whole risk in item 2.** A DSN is a credential. This
module extracts only the *principal* — a username, a role, an account — and never a
password, host, port, database or query string, because "surface the run-as identity" is
one careless f-string away from printing a connection secret into an answer, a receipt, a
log and an exported artifact at once. :func:`run_as_identity` is written as an allowlist of
what may be shown, not a denylist of what must be stripped: a denylist fails open on the
next DSN shape somebody adds, and failing open here means leaking a password.

Read-only and best-effort throughout: a disclosure that cannot be assembled degrades to
"unknown" and never blocks or fails an answer. Governance visibility must not become a new
way for answers to break.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

#: What a run-as identity may contain. An ALLOWLIST on purpose — see the module docstring.
_IDENTITY_SAFE = re.compile(r"^[A-Za-z0-9._@\-]{1,64}$")


@dataclass
class GovernanceDisclosure:
    """What governance did, in terms a reader can act on."""

    run_as: str = "unknown"
    connection_id: str = ""
    standing_grants: list[dict] = field(default_factory=list)
    clearance_trimmed: bool = False
    clearance_notice: str = ""

    @property
    def is_empty(self) -> bool:
        """True when nothing governance-relevant happened worth telling the reader."""
        return (not self.standing_grants and not self.clearance_trimmed
                and self.run_as in ("", "unknown"))

    def lines(self) -> list[str]:
        """Reader-facing lines. Each names a fact and, where relevant, its remedy."""
        out: list[str] = []
        if self.run_as not in ("", "unknown"):
            out.append(f"Ran as `{self.run_as}` on `{self.connection_id}`.")
        for g in self.standing_grants:
            out.append(
                f"Auto-approved by a standing grant: `{g.get('action')}` on "
                f"`{g.get('scope') or '*'}` (granted by {g.get('actor') or 'unknown'}"
                f"{', ' + g['at'] if g.get('at') else ''}) — revocable at "
                f"POST /approvals/revoke.")
        if self.clearance_trimmed and self.clearance_notice:
            out.append(self.clearance_notice)
        return out

    def to_dict(self) -> dict:
        return {"run_as": self.run_as, "connection_id": self.connection_id,
                "standing_grants": list(self.standing_grants),
                "clearance_trimmed": self.clearance_trimmed,
                "clearance_notice": self.clearance_notice,
                "lines": self.lines()}


def _safe_identity(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip()
    return v if v and _IDENTITY_SAFE.match(v) else None


def run_as_identity(conn_type: str, dsn: str) -> str:
    """The PRINCIPAL a connection executes as — never a secret.

    Returns ``"unknown"`` rather than guessing. The allowlist below is what may be shown;
    anything not matched is not displayed, which is the correct direction to fail when the
    alternative is printing a password into an answer.
    """
    ctype = (conn_type or "").strip().lower()
    raw = dsn or ""

    # File-backed connections have no user principal — the process account IS the identity,
    # and naming the OS user would be both wrong and more disclosure than asked for.
    if ctype in ("duckdb", "local_upload", "aughor_ops", "sqlite", ""):
        return f"local ({ctype or 'file'})"

    # URL-style DSNs: postgresql://user:pass@host/db → "user". Parsed with urlsplit rather
    # than a regex over the whole string so a password containing '@' cannot shift what
    # gets captured.
    try:
        from urllib.parse import urlsplit

        parts = urlsplit(raw)
        if parts.username and (ident := _safe_identity(parts.username)):
            return ident
    except Exception as exc:
        # A DSN that will not parse as a URL is ordinary (key=value forms follow), but it
        # is still counted rather than swallowed: a sudden rise here means a connection
        # shape nobody's run-as is being disclosed for, which is exactly the silence this
        # feature exists to remove.
        from aughor.kernel.errors import tolerate

        tolerate(exc, "DSN is not URL-shaped; falling through to key=value parsing",
                 counter="govern.run_as_parse")

    # Key=value DSNs: "user=analytics;password=…" / "UID=analytics;PWD=…".
    for key in ("user", "username", "uid", "account", "role"):
        m = re.search(rf"(?:^|[;\s]){key}\s*=\s*([^;\s]+)", raw, re.IGNORECASE)
        if m and (ident := _safe_identity(m.group(1))):
            return ident

    return "unknown"


def run_as_for(connection_id: str) -> str:
    """The run-as identity for a connection, or ``"unknown"``. Never raises."""
    try:
        from aughor.db.registry import get_dsn

        conn_type, dsn = get_dsn(connection_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "run-as disclosure is best-effort; the answer proceeds",
                 counter="govern.run_as")
        return "unknown"
    return run_as_identity(conn_type, dsn)


def standing_grants_for(action_scopes: Optional[list[tuple[str, str]]] = None) -> list[dict]:
    """The standing grants that covered this run.

    With no ``action_scopes`` the whole allowlist is returned — the "list them" half of
    J2. Given the (action, scope) pairs a run actually took, only the grants that applied
    are returned, which is what belongs on an answer: a reader needs the grant that
    auto-approved *this*, not an inventory.
    """
    try:
        from aughor.govern.actions import list_allowlist

        entries = list_allowlist() or []
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "standing-grant disclosure is best-effort",
                 counter="govern.standing_grants")
        return []

    if action_scopes is None:
        return list(entries)
    wanted = {(a, s or "*") for a, s in action_scopes}
    return [e for e in entries
            if (e.get("action"), e.get("scope") or "*") in wanted]


def build(
    connection_id: str = "",
    *,
    action_scopes: Optional[list[tuple[str, str]]] = None,
    clearance_notice: str = "",
) -> GovernanceDisclosure:
    """Assemble the per-answer disclosure. Never raises; degrades to ``unknown``."""
    return GovernanceDisclosure(
        run_as=run_as_for(connection_id) if connection_id else "unknown",
        connection_id=connection_id,
        standing_grants=standing_grants_for(action_scopes),
        clearance_trimmed=bool(clearance_notice),
        clearance_notice=clearance_notice or "",
    )
