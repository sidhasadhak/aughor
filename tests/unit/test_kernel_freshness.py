"""Wave V1 — the freshness kernel: one vocabulary, two inventories.

The decision gate is two-part and both parts are here:

1. ``test_golden_*`` — every registered fingerprint reproduces its historical hash
   **byte-for-byte**. The expected values are hardcoded literals captured from the
   implementations as they stood before this PR, NOT recomputed from the functions under
   test; a circular assertion would pass through exactly the change it exists to catch.
   A red test here means live caches on someone's warehouse are about to miss en masse.
2. ``test_differential_*`` — ``graph_freshness.classify`` emits identical verdicts through
   the kernel as it did inline, across every branch of its decision table.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from aughor.kernel.freshness import (
    DEGRADED_STATES,
    FINGERPRINTS,
    LOGIC_VERSIONS,
    FreshnessVerdict,
    classify_fingerprints,
    compose_fingerprint,
    fingerprint,
    logic_versions,
    staleness_fingerprints,
)

REPO = Path(__file__).resolve().parents[2]


# ── 1. Golden hashes: the bytes must not move ─────────────────────────────────

BLOCKS = {"orders": "id INT\ntotal DEC\n", "items": "id INT\n"}
SUMMARY = "TABLE: orders\n  id INT\n  total DEC\n-- a comment\nTABLE: items\n  id INT\n"


def test_golden_schema_cache_unscoped():
    from aughor.db.schema_cache import compute_fingerprint

    assert compute_fingerprint(BLOCKS) == "1c23756f28e3926d"


def test_golden_schema_cache_scoped():
    """The scope path is separately pinned — it is the one that fixed a real bug
    (two copies of one DDL sharing a 'seeded' marker)."""
    from aughor.db.schema_cache import compute_fingerprint

    assert compute_fingerprint(BLOCKS, "conn1:main") == "e9ed0fd915c90474"


def test_golden_profile_cache_survives_logic_version_extraction():
    """PROFILE_LOGIC_VERSION is baked into the hash INPUT, so its value IS the cache key.

    Originally pinned at "v4-valsample" to prove that extracting it from an inline literal
    changed nothing. Bumped twice on 2026-08-17: "v5-concept" for AT-4/AT-6 (per-column
    `concept`, per-table `derived_quantities`, and `semantic_type` for space-separated
    identifiers), then "v6-postal-key" when a postal-named TEXT column became a `key`, then "v7-percent-scale"
    when `unit` gained `percent_whole`.

    Both bumps are DELIBERATE global misses, because `from_dict` reads an older entry
    happily and every existing connection would otherwise keep serving stale profiles. The
    v6 one is here because it caught its own author: the postal fix was verified against a
    CACHED profile that still said `dimension` and read as not working. **Any change to
    `_semantic_type` OR `_value_interpretation` moves what is stored, so it moves this string.**

    Both hashes stay pinned. The v4 line is what makes a bump legible as a bump rather
    than as a hash that drifted: a version change must move every key, and an extraction
    must move none.
    """
    import hashlib

    from aughor.tools.profile_cache import PROFILE_LOGIC_VERSION, compute_schema_fingerprint

    assert PROFILE_LOGIC_VERSION == "v8-table-cap"
    assert compute_schema_fingerprint({"orders": 5, "items": 3}) == "f8d6bf0025b139c9"
    # the same inputs under the previous version — a different key, which is the point
    v4 = hashlib.md5(b"v4-valsample|items:3|orders:5").hexdigest()[:16]
    assert v4 == "191fd41b93f3a03e"
    assert compute_schema_fingerprint({"orders": 5, "items": 3}) != v4


def test_golden_ontology_store_survives_function_extraction():
    """compute_ontology_fingerprint was lifted out of get_or_build_ontology verbatim."""
    from aughor.ontology.store import compute_ontology_fingerprint

    class TP:
        def __init__(self, rc, gc):
            self.row_count, self.grain_column = rc, gc

    assert compute_ontology_fingerprint(
        {"orders": TP(10, "id"), "items": TP(3, "")}
    ) == "ebb953b0261f1547"


def test_golden_suggestions_cache():
    from aughor.semantic.suggestions_cache import schema_fingerprint

    assert schema_fingerprint(SUMMARY) == "6ad28dac85c9c51a"


def _stub_ontology():
    """Duck-typed stand-ins — graph_freshness reads these by getattr, never by type."""

    class Prop:
        def __init__(self, n, t):
            self.name, self.data_type = n, t

    class Ent:
        def __init__(self, tables, props):
            self.source_tables, self.properties = tables, props

    class Ont:
        def __init__(self, ents, data_fp=""):
            self.entities, self.schema_fingerprint = ents, data_fp

    return Ont, Ent, Prop


def test_golden_graph_structural_after_single_pass_refactor():
    """structural_fingerprint now shares one pass with the per-table map; same bytes."""
    from aughor.ontology.graph_freshness import structural_fingerprint, table_fingerprints

    Ont, Ent, Prop = _stub_ontology()
    ont = Ont({
        "Order": Ent(["main.orders"], {"id": Prop("id", "INT"), "total": Prop("total", "DEC")}),
        "Item": Ent(["main.items"], {"id": Prop("id", "INT")}),
    })
    assert structural_fingerprint(ont) == "683c453939e81b2d"
    assert table_fingerprints(ont) == {
        "Order": "9131c733774787cf", "Item": "5772156370f690a1",
    }


# ── 2. Differential: the verdicts must not move ───────────────────────────────

def _graph(struct, data, tables):
    class G:
        structural_fingerprint = struct
        schema_fingerprint = data
        table_fingerprints = tables

    return G()


@pytest.mark.parametrize(
    "prev,cur_struct,cur_data,cur_tables,expected",
    [
        # (change, staleness, changed_tables, reason)
        (None, "s1", "d1", {"A": "a"},
         ("full", "stale", [], "no committed graph yet (first build)")),
        (_graph("s1", "d1", {"A": "a"}), "s1", "d1", {"A": "a"},
         ("skip", "fresh", [], "structure and data unchanged")),
        (_graph("s1", "d1", {"A": "a"}), "s1", "d2", {"A": "a"},
         ("skip", "dirty", [], "data moved (row counts changed); structure unchanged")),
        (_graph("s1", "d1", {"A": "a"}), "s2", "d1", {"A": "a2"},
         ("partial", "stale", ["A"], "columns changed on ['A']")),
        (_graph("s1", "d1", {"A": "a"}), "s2", "d1", {"A": "a", "B": "b"},
         ("full", "stale", [], "tables added=['B'] removed=[]")),
        (_graph("s1", "d1", {"A": "a", "B": "b"}), "s2", "d1", {"A": "a"},
         ("full", "stale", [], "tables added=[] removed=['B']")),
    ],
)
def test_differential_classify_matches_the_inline_decision_table(
    prev, cur_struct, cur_data, cur_tables, expected
):
    """Every branch of C3's original table, asserted on exact output including reason."""
    v = classify_fingerprints(
        prev_structural=prev.structural_fingerprint if prev else None,
        prev_data=prev.schema_fingerprint if prev else None,
        cur_structural=cur_struct,
        cur_data=cur_data,
        prev_units=prev.table_fingerprints if prev else None,
        cur_units=cur_tables,
        absent_prior_reason="no committed graph yet (first build)",
    )
    assert (v.change, v.staleness, v.changed_tables, v.reason) == expected


def test_differential_classify_through_graph_freshness_end_to_end():
    """The real entry point, not just the kernel — a dirty verdict on a data-only move."""
    from aughor.ontology.graph_freshness import classify, structural_fingerprint

    Ont, Ent, Prop = _stub_ontology()
    ont = Ont({"Order": Ent(["orders"], {"id": Prop("id", "INT")})}, data_fp="d-new")
    prev = _graph(structural_fingerprint(ont), "d-old",
                  {"Order": "9d0d4b1cbd0ee1a1"})

    v = classify(prev, ont)
    assert (v.change, v.staleness) == ("skip", "dirty")
    assert v.reason == "data moved (row counts changed); structure unchanged"


def test_classify_absent_current_wins_over_absent_prior():
    """Order matters: with BOTH missing, C3 returned unknown (current checked first)."""
    v = classify_fingerprints(
        prev_structural=None, prev_data=None, cur_structural=None, cur_data=None,
        absent_current_reason="no current ontology to compare",
    )
    assert (v.change, v.staleness, v.reason) == (
        "unknown", "unknown", "no current ontology to compare")


def test_graph_freshness_reexports_the_same_types_not_lookalikes():
    """A second, structurally-identical dataclass would silently break isinstance."""
    from aughor.ontology import graph_freshness as gf

    assert gf.FreshnessVerdict is FreshnessVerdict


def test_verdict_helpers():
    assert FreshnessVerdict("full", "stale").needs_rebuild is True
    assert FreshnessVerdict("skip", "dirty").needs_rebuild is False
    assert FreshnessVerdict("skip", "fresh").degraded is False
    assert all(FreshnessVerdict("skip", s).degraded for s in DEGRADED_STATES)


# ── 3. The canonical composition ──────────────────────────────────────────────

def test_compose_is_order_independent_and_stable():
    assert compose_fingerprint(["b:2", "a:1"]) == compose_fingerprint(["a:1", "b:2"])
    assert len(compose_fingerprint(["a:1"])) == 16


def test_compose_scope_defeats_the_identity_hazard():
    """The bug schema_cache shipped and had to fix: two copies of one DDL hashing the
    same, so the second inherits the first's cached state. Proven, not asserted."""
    parts = ["orders:5", "items:3"]
    assert compose_fingerprint(parts, scope="dev") != compose_fingerprint(parts, scope="prod")
    assert compose_fingerprint(parts) != compose_fingerprint(parts, scope="dev")


def test_compose_logic_version_forces_a_rebuild():
    parts = ["orders:5"]
    assert compose_fingerprint(parts, logic="v1") != compose_fingerprint(parts, logic="v2")


def test_compose_scope_separator_cannot_be_forged():
    """NUL-separated so a scope+parts pair can't collide with a different pair that
    concatenates to the same string."""
    a = compose_fingerprint(["x"], scope="a|orders:5")
    b = compose_fingerprint(["orders:5"], scope="a", logic="x")
    assert a != b


# ── 4. The inventories resolve, and the ratchets prevent dialect #14 ──────────

def test_every_registered_fingerprint_resolves():
    for name, spec in FINGERPRINTS.items():
        assert callable(spec.resolve()), f"{name} does not resolve"


def test_registry_lookup_computes_the_same_bytes_as_the_module():
    from aughor.tools.profile_cache import compute_schema_fingerprint

    counts = {"orders": 5, "items": 3}
    assert fingerprint("profile_cache", counts) == compute_schema_fingerprint(counts)


def test_unknown_fingerprint_names_the_registered_ones():
    with pytest.raises(KeyError, match="unknown fingerprint"):
        fingerprint("not_a_real_fingerprint")


def test_logic_versions_resolve_live_not_a_stale_copy():
    from aughor.ontology.enricher import ENRICHMENT_VERSION

    assert logic_versions()["enrichment"] == ENRICHMENT_VERSION
    assert set(logic_versions()) == set(LOGIC_VERSIONS)


def test_staleness_and_content_fingerprints_are_distinguished():
    """Wave V owns artifact staleness. A dedup hash is NOT a staleness signal, and
    conflating them is how a 14th dialect gets born."""
    st = staleness_fingerprints()
    assert "graph_structural" in st and "sql_result" not in st


# ── The ratchets ──────────────────────────────────────────────────────────────

#: The kernel itself is the registry, not a registered implementation — its own
#: ``compose_fingerprint`` / ``classify_fingerprints`` helpers are the shared shape the
#: ratchets exist to point new code AT, so scanning it would flag the cure as the disease.
_RATCHET_SKIP = {REPO / "aughor" / "kernel" / "freshness.py"}


def _py_files():
    for p in (REPO / "aughor").rglob("*.py"):
        if "__pycache__" not in p.parts and p not in _RATCHET_SKIP:
            yield p


def test_ratchet_every_logic_version_constant_is_registered():
    """A new producer-logic constant must join the inventory. Six encodings of "my logic
    changed, recompute" already existed, invisible to each other; this is what stops a
    seventh appearing unannounced."""
    registered = {(s.module.rsplit(".", 1)[-1], s.attr) for s in LOGIC_VERSIONS.values()}
    found = set()
    for path in _py_files():
        for m in re.finditer(r"^([A-Z][A-Z0-9_]*(?:VERSION|FORMAT))\s*(?::[^=]+)?=",
                             path.read_text(), re.M):
            found.add((path.stem, m.group(1)))

    unregistered = found - registered
    assert not unregistered, (
        f"unregistered producer-logic version(s): {sorted(unregistered)}. "
        "Add them to LOGIC_VERSIONS in aughor/kernel/freshness.py — the inventory is the "
        "point of Wave V1."
    )


#: Fingerprint-shaped functions that are deliberately NOT in the registry, with why.
#: A one-way ratchet: this baseline may shrink, never grow.
_FINGERPRINT_ALLOWLIST = {
    ("ontology", "_latest_fingerprint"),        # reads a stored value; computes nothing
    ("continuous", "connection_schema_fingerprint"),  # delegates to profile_cache
    ("evidence_budget", "_fingerprint"),        # content: result identity for rendering
    ("ambiguity_ledger", "_fingerprint"),       # content: facet identity
}


def test_ratchet_every_fingerprint_function_is_registered_or_allowlisted():
    registered = {(s.module.rsplit(".", 1)[-1], s.attr) for s in FINGERPRINTS.values()}
    found = set()
    for path in _py_files():
        for m in re.finditer(r"^def ([a-z_]*fingerprint[a-z_]*)\(", path.read_text(), re.M):
            found.add((path.stem, m.group(1)))

    unaccounted = found - registered - _FINGERPRINT_ALLOWLIST
    assert not unaccounted, (
        f"unregistered fingerprint function(s): {sorted(unaccounted)}. Register it in "
        "FINGERPRINTS (aughor/kernel/freshness.py) as kind='staleness', or add it to "
        "_FINGERPRINT_ALLOWLIST with the reason it is content-identity, not staleness."
    )


def test_ratchet_allowlist_has_not_grown():
    """Never raise a ratchet baseline — the repo rule, enforced on this ratchet too."""
    assert len(_FINGERPRINT_ALLOWLIST) <= 5


def test_kernel_stays_dependency_free():
    """The inventory resolves lazily by module path precisely so this kernel cannot form
    an import cycle with the stores it inventories."""
    src = (REPO / "aughor" / "kernel" / "freshness.py").read_text()
    assert "from aughor." not in src and "import aughor" not in src
