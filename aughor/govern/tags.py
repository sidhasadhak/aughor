"""Wave G2 — governed tags on securables, and the clearances that read them.

**What a tag is.** A namespaced key-value fact attached to a securable — a catalog, a
schema, a table, or an artifact — recorded with who set it and when. ``pii=true``,
``tier=restricted``, ``domain=finance``. Tags are *governed*: a human or a declared
process sets them, and the record says which. Nothing here infers a tag from data, and
nothing here lets a model author one (J4 is not a graph-only rule).

**What a clearance is.** A string a principal holds. A tag becomes *load-bearing* when a
policy says the tag requires a clearance; a principal without it does not clear the
securable. That is the whole model, and it is deliberately smaller than roles.

**Why clearances are a THIRD axis rather than a replacement.** The program scoped G2 as
"tags and clearances **before roles**, roles come later" — written when RBAC was P1 and
unenforced. It is not: ``aughor/rbac/policy.py`` is P4 and ``enforce_rbac`` is wired
app-wide at ``aughor/api.py:171``, so roles ship and are enforced on every request. The
axes therefore compose with AND, and each answers a different question:

    licensing capability  what the org's PLAN unlocks
    RBAC permission       what this USER may do
    clearance (this)      what this DATA requires of whoever reads it

A role says "analysts may run analyses". A clearance says "and not over the salary
table". Neither expresses the other, which is why the third axis earns its keep.

**The refusal is never silence.** ``evaluate`` returns a decision that NAMES what blocked
it and which clearance would unblock it. R4's rule, and the pinned anti-pattern from the
Genie teardown: a permission-trimmed answer that comes back empty teaches its reader that
the data does not exist. A caller may withhold the rows; it must not withhold the reason.

Deterministic and pure: :func:`evaluate` takes the tags and the clearances and returns a
decision. Reading them from a store is the caller's half, so the policy is testable
without a database and cannot silently depend on one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from aughor.metastore.models import securable_kind

#: Tag keys this module understands as access-controlling. Everything else is a
#: descriptive tag — real, stored, queryable, and NOT a gate. Keeping the gating set
#: small and explicit is what stops "we tagged it" from silently meaning "we secured it".
GATING_KEYS: frozenset[str] = frozenset({"tier", "pii"})

#: The clearance a ``tier`` value demands. A tier absent from this map does not gate —
#: an unknown tier is a DESCRIPTION, not a lock, because inventing a lock from an
#: unrecognised string would make a typo silently deny access to real data.
TIER_CLEARANCE: dict[str, str] = {
    "restricted": "clearance.restricted",
    "confidential": "clearance.confidential",
}

#: The clearance ``pii=true`` demands.
PII_CLEARANCE = "clearance.pii"


@dataclass(frozen=True)
class Tag:
    """One governed key-value on one securable, with the provenance that makes it evidence."""

    securable: str
    key: str
    value: str
    set_by: str = ""            # the principal who set it — never a model
    set_at: str = ""
    source: str = "human"       # "human" | "policy" | "import"

    def to_dict(self) -> dict:
        return {"securable": self.securable, "key": self.key, "value": self.value,
                "set_by": self.set_by, "set_at": self.set_at, "source": self.source}


@dataclass(frozen=True)
class Requirement:
    """One reason a securable is gated: the tag, and the clearance that satisfies it."""

    key: str
    value: str
    clearance: str

    def describe(self) -> str:
        return f"{self.key}={self.value} requires {self.clearance}"


@dataclass
class ClearanceDecision:
    """Whether a principal clears a securable — and, when not, exactly why.

    ``allowed`` is the answer. ``missing`` is the part a caller MUST surface: an empty
    result with no reason is the anti-pattern this whole axis exists to avoid.
    """

    securable: str
    allowed: bool
    requirements: list[Requirement] = field(default_factory=list)  # every gate that applied
    missing: list[Requirement] = field(default_factory=list)       # the ones not satisfied

    @property
    def reason(self) -> str:
        """A sentence fit to put in front of a user, naming what would unblock them.

        Deliberately concrete about the clearance and vague about nothing: a reader who
        cannot see the data should still learn that it exists and what to ask for.
        """
        if self.allowed:
            return ""
        needs = ", ".join(sorted({r.clearance for r in self.missing}))
        return (f"Withheld by data governance: {self.securable} is tagged "
                f"{', '.join(sorted(r.describe() for r in self.missing))}. "
                f"Access requires {needs}.")

    def to_dict(self) -> dict:
        return {"securable": self.securable, "allowed": self.allowed,
                "requirements": [r.describe() for r in self.requirements],
                "missing": [r.describe() for r in self.missing],
                "reason": self.reason}


def requirements_for(tags: Iterable[Tag]) -> list[Requirement]:
    """The gates a securable's tags impose — deterministic, order-stable.

    Only :data:`GATING_KEYS` gate. A ``domain=finance`` tag is a fact about the object and
    changes nothing about who may read it; conflating the two would mean every descriptive
    tag anyone adds quietly becomes a lock.
    """
    out: list[Requirement] = []
    for tag in tags:
        key, value = tag.key.strip().lower(), str(tag.value).strip().lower()
        if key not in GATING_KEYS:
            continue
        if key == "tier" and (clearance := TIER_CLEARANCE.get(value)):
            out.append(Requirement(key="tier", value=value, clearance=clearance))
        elif key == "pii" and value in ("true", "1", "yes"):
            out.append(Requirement(key="pii", value="true", clearance=PII_CLEARANCE))
    return sorted(set(out), key=lambda r: (r.key, r.value))


def evaluate(
    securable: str,
    tags: Iterable[Tag],
    clearances: Iterable[str],
    *,
    bypass: bool = False,
) -> ClearanceDecision:
    """Does a principal holding ``clearances`` clear ``securable``?

    ``bypass`` is for the owner ladder — the caller decides who bypasses (this module has
    no opinion about roles), but it is threaded through the SAME function rather than
    letting callers skip the check, so an audited decision exists either way and a bypass
    is visible in the receipt instead of being an absent call.

    An untagged securable is allowed: governance is opt-in per object, and defaulting to
    deny would make enabling the flag a platform-wide outage rather than a policy.
    """
    reqs = requirements_for(tags)
    held = {str(c).strip().lower() for c in clearances if str(c).strip()}
    missing = [] if bypass else [r for r in reqs if r.clearance.lower() not in held]
    return ClearanceDecision(securable=securable, allowed=not missing,
                             requirements=reqs, missing=missing)


def enabled() -> bool:
    """Whether clearance enforcement is live. Off ⇒ every caller's decision is ALLOW.

    Read at call time, never at import: a module-level constant would make a test's
    ``monkeypatch.setenv`` a silent no-op, which this repo has already paid for once when
    the eval suite spent real LLM budget against a flag it believed was off.
    """
    from aughor.kernel.flags import flag_enabled

    return flag_enabled("govern.clearances")


def check(
    securable: str,
    clearances: Iterable[str],
    *,
    org_id: Optional[str] = None,
    bypass: bool = False,
) -> ClearanceDecision:
    """The store-backed convenience wrapper: read the tags, then :func:`evaluate`.

    Returns an ALLOW decision with no requirements when the flag is off, so a caller can
    wire this in unconditionally and the off state is byte-identical to not calling it.
    """
    if not enabled():
        return ClearanceDecision(securable=securable, allowed=True)
    from aughor.govern.tag_store import tags_for

    return evaluate(securable, tags_for(securable, org_id=org_id), clearances, bypass=bypass)


def gating_kinds() -> tuple[str, ...]:
    """The securable kinds a tag may name — mirrors the metastore vocabulary."""
    return ("catalog", "schema", "table", "artifact")


def is_securable(value: str) -> bool:
    """Whether ``value`` is a well-formed securable string this plane can tag."""
    return bool(securable_kind(value))
