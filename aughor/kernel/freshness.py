"""One vocabulary for "is this artifact out of date?" — Wave V1.

Wave V's survey found **thirteen** incompatible dialects of staleness in this tree, only
one of which (Wave C3's graph freshness) was typed. This module is the consolidation:
the C3 vocabulary lifted to the kernel so briefs, profiles and caches can speak it too,
plus two inventories that make the *next* dialect hard to add by accident.

What it does NOT do — deliberately:

* **It does not converge the fingerprints' bytes.** Five stores hash a schema five
  incomparable ways. Unifying their hash *inputs* would change every key at once, which
  is a silent mass cache-miss — an expensive rebuild on a user's warehouse, invisible
  until the bill. The registry below unifies the *lookup and the documentation*; each
  adapter still produces exactly the bytes it always did, pinned by a golden test.
* **It does not abolish caching.** A wall-clock TTL is right for genuinely time-bound
  things, and a watermark's ``>`` is right where ``!=`` is not (``automations/probes.py``
  argues this deliberately). This module owns *artifact staleness*, nothing else.
* **It does not touch business data-freshness** (SLA lag hours, ``monitors/runner.py``).
  That axis shares the word "stale" and nothing else; keeping them apart is the point.

Additive and inert: importing this module changes no behaviour. It has no flag because
it gates no behaviour — V1 is a consolidation, and the first *gated* behaviour arrives in
V2 (staleness-resolved rebuild). A flag that switches nothing is the flag-drift this
codebase has already paid for once.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from importlib import import_module
from typing import Callable, Iterable, Literal, Mapping, Optional

# ── The vocabulary (lifted from ontology/graph_freshness.py — Wave C3) ────────

#: What a refresh should DO about a change.
ChangeClass = Literal["skip", "partial", "full", "unknown"]
#: How trustworthy the stored artifact reads RIGHT NOW against its source.
StalenessState = Literal["fresh", "dirty", "stale", "unknown"]

#: The states a consumer should treat as "answer, but say it may lag". Mirrors the
#: pack envelope's ``degraded`` flag (Wave C6) so prose and code agree.
DEGRADED_STATES: tuple[StalenessState, ...] = ("dirty", "stale", "unknown")


@dataclass
class FreshnessVerdict:
    """The typed answer to "is this out of date, and what should I do about it?".

    ``changed_tables`` keeps C3's name rather than an abstract ``changed_units``: in this
    platform the unit of change genuinely *is* a table, for the graph as for profiles and
    briefs, and renaming it would break callers to buy nothing.
    """

    change: ChangeClass          # what refresh should DO
    staleness: StalenessState    # how the stored artifact reads RIGHT NOW
    changed_tables: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def needs_rebuild(self) -> bool:
        return self.change in ("partial", "full")

    @property
    def degraded(self) -> bool:
        """True when a consumer should carry a caveat (anything but ``fresh``)."""
        return self.staleness in DEGRADED_STATES


def classify_fingerprints(
    *,
    prev_structural: Optional[str],
    prev_data: Optional[str],
    cur_structural: Optional[str],
    cur_data: Optional[str],
    prev_units: Optional[Mapping[str, str]] = None,
    cur_units: Optional[Mapping[str, str]] = None,
    absent_current_reason: str = "no current state to compare",
    absent_prior_reason: str = "no stored artifact yet (first build)",
    unit_noun: str = "tables",
    sub_unit_noun: str = "columns",
) -> FreshnessVerdict:
    """The generic staleness decision, extracted from C3 so every artifact shares it.

    The load-bearing idea is the **two-fingerprint split**: a *structural* fingerprint
    (tables + columns + types, nothing data-dependent) and a *data* fingerprint (row
    counts and the like). Keeping them apart is what lets the verdict be honest — a
    nightly reload moves the data fingerprint but not the structural one, so it marks the
    artifact **dirty** (surface it) rather than **stale** (rebuild it). Collapsing them
    into one hash is what makes a system rebuild all night for nothing.

    Decision table:

    ==========================  ==========================  ====================
    structural                  data                        verdict
    ==========================  ==========================  ====================
    current missing             —                           unknown / unknown
    prior missing               —                           full / stale
    equal                       equal                       skip / fresh
    equal                       moved                       skip / **dirty**
    moved, same unit set        —                           partial / stale
    moved, unit set changed     —                           full / stale
    ==========================  ==========================  ====================
    """
    if cur_structural is None:
        return FreshnessVerdict("unknown", "unknown", reason=absent_current_reason)
    if prev_structural is None:
        return FreshnessVerdict("full", "stale", reason=absent_prior_reason)

    if cur_structural == (prev_structural or ""):
        if (cur_data or "") == (prev_data or ""):
            return FreshnessVerdict("skip", "fresh", reason="structure and data unchanged")
        # A reload / backfill: the structure the artifact encodes is still correct, but it
        # rests on data that moved. Surface it; do NOT rebuild.
        return FreshnessVerdict(
            "skip", "dirty",
            reason="data moved (row counts changed); structure unchanged",
        )

    cur_u = dict(cur_units or {})
    prev_u = dict(prev_units or {})
    added = set(cur_u) - set(prev_u)
    removed = set(prev_u) - set(cur_u)
    changed = [k for k in cur_u if k in prev_u and cur_u[k] != prev_u[k]]

    if added or removed:
        return FreshnessVerdict(
            "full", "stale", changed_tables=sorted(changed),
            reason=f"{unit_noun} added={sorted(added)} removed={sorted(removed)}",
        )
    return FreshnessVerdict(
        "partial", "stale", changed_tables=sorted(changed),
        reason=f"{sub_unit_noun} changed on {sorted(changed)}",
    )


# ── The canonical fingerprint composition (for NEW stores) ────────────────────

def compose_fingerprint(
    parts: Iterable[str], *, scope: str = "", logic: str = ""
) -> str:
    """The composition a *new* staleness fingerprint should use.

    ``md5`` over sorted, ``|``-joined parts, truncated to 16 hex chars — the shape all
    five existing implementations already converged on by accident.

    Two prefixes, both load-bearing, both learned the hard way:

    * ``scope`` — **structure alone does not identify an artifact.** Two copies of one
      DDL (a dev and a prod database, two tenants, two schemas in one workspace) project
      to identical parts, so without a scope the second silently inherits the first's
      cached state. ``db/schema_cache.py:32-39`` documents exactly this bug being fixed
      after it shipped. NUL-separated, because no identifier can contain a NUL, so no
      ``scope + parts`` pair can collide with a different pair that concatenates the same.
    * ``logic`` — **the producer's own version.** When the code that builds the artifact
      changes shape, every stored copy is stale even though the source did not move.
      Registered in :data:`LOGIC_VERSIONS` rather than invented per module.

    Existing stores do NOT call this — their bytes are frozen (see the module docstring).
    """
    raw = "|".join(sorted(parts))
    if logic:
        raw = f"{logic}|{raw}"
    if scope:
        raw = f"{scope}\x00{raw}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


# ── Inventory 1: the fingerprint implementations ──────────────────────────────

#: ``staleness`` — answers "is the stored artifact out of date?" (Wave V's subject).
#: ``content``   — identifies a value for dedup/idempotency; NOT a staleness signal.
FingerprintKind = Literal["staleness", "content"]


@dataclass(frozen=True)
class FingerprintSpec:
    """One registered fingerprint, resolved lazily.

    Lazy by module path rather than an imported callable so this kernel module stays
    dependency-free and cannot create an import cycle with the stores it inventories.
    """

    name: str
    module: str
    attr: str
    kind: FingerprintKind
    note: str = ""

    def resolve(self) -> Callable:
        return getattr(import_module(self.module), self.attr)


#: Every fingerprint function in the tree, with the reason it exists. This inventory IS
#: the deliverable: before it, five staleness fingerprints had drifted into three
#: different conventions for the same identity hazard and no reader could tell which was
#: authoritative. A ratchet test fails when a new one appears unregistered.
FINGERPRINTS: dict[str, FingerprintSpec] = {
    spec.name: spec
    for spec in (
        # ── staleness: "is the stored artifact out of date?" ──
        FingerprintSpec(
            "schema_cache", "aughor.db.schema_cache", "compute_fingerprint", "staleness",
            "autoseed's 'fully seeded' marker. Scope folded INTO the hash (NUL-separated) "
            "after two copies of one DDL shared a marker.",
        ),
        FingerprintSpec(
            "profile_cache", "aughor.tools.profile_cache", "compute_schema_fingerprint",
            "staleness",
            "table profiles. Structure-only hash; identity lives in the CACHE KEY "
            "({conn}:{fp}) instead of the hash — a different convention from schema_cache "
            "for the same hazard. Carries its logic version as a literal prefix.",
        ),
        FingerprintSpec(
            "ontology_store", "aughor.ontology.store", "compute_ontology_fingerprint",
            "staleness",
            "the ontology cache key. Folds row_count IN, so it moves on every reload — "
            "which is why C3 had to add a separate STRUCTURAL fingerprint.",
        ),
        FingerprintSpec(
            "suggestions_cache", "aughor.semantic.suggestions_cache", "schema_fingerprint",
            "staleness",
            "starter-question cache. Hashes structural LINES parsed out of a rendered "
            "schema summary, not a projection of the schema itself.",
        ),
        FingerprintSpec(
            "graph_structural", "aughor.ontology.graph_freshness", "structural_fingerprint",
            "staleness",
            "Wave C3's structural half — tables + columns + types, no row counts. The "
            "only one designed as half of a deliberate two-fingerprint split.",
        ),
        FingerprintSpec(
            "graph_per_table", "aughor.ontology.graph_freshness", "table_fingerprints",
            "staleness",
            "per-entity structural hashes, so a PARTIAL verdict can name which tables moved.",
        ),
        # ── content: identity for dedup / idempotency, NOT staleness ──
        FingerprintSpec(
            "sql_args", "aughor.agent.wandering", "args_fingerprint", "content",
            "detects an agent re-running the same SQL (the wandering detector).",
        ),
        FingerprintSpec(
            "sql_result", "aughor.agent.wandering", "result_fingerprint", "content",
            "detects an agent re-deriving the same result set.",
        ),
    )
}


def fingerprint(name: str, *args, **kwargs) -> object:
    """Compute a registered fingerprint by name — the unified lookup.

    The bytes are whatever that store has always produced; this only removes the need to
    know which module owns which hash.
    """
    spec = FINGERPRINTS.get(name)
    if spec is None:
        raise KeyError(
            f"unknown fingerprint {name!r}. Registered: {sorted(FINGERPRINTS)}. "
            "A new staleness fingerprint must be registered here (see the ratchet test)."
        )
    return spec.resolve()(*args, **kwargs)


def staleness_fingerprints() -> dict[str, FingerprintSpec]:
    """Only the ones that answer "is this out of date?" — Wave V's subject."""
    return {k: v for k, v in FINGERPRINTS.items() if v.kind == "staleness"}


# ── Inventory 2: the producer-logic versions ──────────────────────────────────

@dataclass(frozen=True)
class LogicVersionSpec:
    """A producer's own version — bumped when its output shape changes, so stored copies
    are rebuilt even though the source data never moved."""

    name: str
    module: str
    attr: str
    note: str = ""

    def value(self) -> object:
        return getattr(import_module(self.module), self.attr)


#: The six ad-hoc encodings of "my logic changed, recompute", in one place. Values are
#: NOT changed here — changing one would trigger the very rebuild storm V1 exists to
#: avoid. This is an inventory, not a migration.
LOGIC_VERSIONS: dict[str, LogicVersionSpec] = {
    spec.name: spec
    for spec in (
        LogicVersionSpec("enrichment", "aughor.ontology.enricher", "ENRICHMENT_VERSION",
                         "cached graphs below this are re-enriched."),
        LogicVersionSpec("validation", "aughor.ontology.validator", "VALIDATION_VERSION",
                         "cached graphs below this are re-validated."),
        LogicVersionSpec("dossier", "aughor.explorer.dossier", "DOSSIER_VERSION",
                         "finding-dossier payload shape."),
        LogicVersionSpec("graph_pack", "aughor.ontology.context_graph_export", "PACK_FORMAT",
                         "Wave C6 export envelope; a consumer refuses a format it can't read."),
        LogicVersionSpec("public_receipt", "aughor.trust.receipt", "PUBLIC_RECEIPT_VERSION",
                         "the public trust-receipt shape."),
        LogicVersionSpec("profile_cache", "aughor.tools.profile_cache", "PROFILE_LOGIC_VERSION",
                         "the odd one out: baked into the hash INPUT as a literal prefix "
                         "rather than compared as a version."),
        LogicVersionSpec("ontology_bundle", "aughor.ontology.interchange", "BUNDLE_VERSION",
                         "Wave O7 connection-as-code interchange shape; an importer refuses "
                         "a bundle newer than it understands rather than half-applying it."),
        LogicVersionSpec("briefing", "aughor.knowledge.briefing", "BRIEFING_LOGIC_VERSION",
                         "the narrative's shape; bumping it regenerates cached briefs whose "
                         "source data never moved (Wave V2's logic half)."),
    )
}


def logic_versions() -> dict[str, object]:
    """Resolve every registered producer-logic version to its live value."""
    return {name: spec.value() for name, spec in LOGIC_VERSIONS.items()}
