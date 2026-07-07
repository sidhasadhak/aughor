"""Canonical metric resolver — reconciliation precedence + injection safety.

Ensures "revenue" resolves to ONE formula across stores so /chat and ADA can't diverge.
See aughor/semantic/canonical.py.
"""
from types import SimpleNamespace

from aughor.semantic.canonical import (
    resolve_canonical_metrics,
    render_canonical_metrics_block,
)


def _md(name, sql, **kw):  # MetricDefinition stub (catalog)
    return SimpleNamespace(name=name, label=kw.get("label", name), sql=sql,
                           unit=kw.get("unit", ""), tables=kw.get("tables", []),
                           caveats=kw.get("caveats", ""))


def _om(mid, sql, verified=False, **kw):  # OntologyMetric stub
    return SimpleNamespace(id=mid, display_name=kw.get("display_name", mid),
                           formula_sql=sql, unit=kw.get("unit", ""),
                           tables=kw.get("tables", []), verified=verified)


def _onto(*metrics):  # OntologyGraph stub
    return SimpleNamespace(metrics={m.id: m for m in metrics})


def test_catalog_outranks_ontology():
    catalog = [_md("revenue", "SUM(price*qty)")]
    onto = _onto(_om("revenue", "SUM(invoices.revenue_net)", verified=True))
    res = resolve_canonical_metrics(catalog=catalog, ontology=onto)
    rev = {m.name: m for m in res}["revenue"]
    assert rev.sql == "SUM(price*qty)", rev.sql          # curated catalog wins
    assert rev.source == "catalog"


def test_ontology_verified_flag_drives_source_and_injectability():
    # The ontology keys metrics by id, so the verified flag governs source rank +
    # whether the formula is injectable as authoritative (not within-ontology dedup).
    onto = _onto(
        _om("aov", "SUM(amount)/COUNT(DISTINCT order_id)", verified=True),
        _om("margin", "SUM(profit)/SUM(revenue)", verified=False),
    )
    res = {m.name: m for m in resolve_canonical_metrics(catalog=[], ontology=onto)}
    assert res["aov"].source == "ontology_verified" and res["aov"].verified
    assert res["margin"].source == "ontology_unverified" and not res["margin"].verified
    block = render_canonical_metrics_block(list(res.values()))
    assert "aov" in block            # verified → injected
    assert "margin" not in block     # unverified → excluded


def test_source_rank_ordering():
    from aughor.semantic.canonical import CanonicalMetric
    ranks = [CanonicalMetric("m", "m", "x", source=s).rank
             for s in ("catalog", "ontology_verified", "ontology_unverified")]
    assert ranks == sorted(ranks, reverse=True) and len(set(ranks)) == 3


def test_dedup_by_normalized_name():
    catalog = [_md("Net Revenue", "SUM(net)")]
    onto = _onto(_om("net_revenue", "SUM(gross)", verified=True))
    res = resolve_canonical_metrics(catalog=catalog, ontology=onto)
    names = [m.name for m in res]
    assert len(res) == 1, names           # "Net Revenue" and "net_revenue" collapse
    assert res[0].sql == "SUM(net)"       # catalog precedence


def test_render_excludes_unverified_by_default():
    onto = _onto(_om("churn", "1 - retention", verified=False))
    res = resolve_canonical_metrics(catalog=[], ontology=onto)
    assert render_canonical_metrics_block(res) == ""   # unverified not injected as authoritative
    block = render_canonical_metrics_block(res, include_unverified=True)
    assert "churn" in block and "unverified" in block


def test_render_lists_verified_with_exact_formula():
    catalog = [_md("revenue", "SUM(price*qty)", unit="$")]
    res = resolve_canonical_metrics(catalog=catalog, ontology=None)
    block = render_canonical_metrics_block(res)
    assert "revenue [$] = SUM(price*qty)" in block
    assert "use these EXACT formulas" in block


def test_empty_is_noop_safe():
    assert resolve_canonical_metrics(catalog=[], ontology=None) == []
    assert render_canonical_metrics_block([]) == ""


def test_metrics_without_sql_are_skipped():
    res = resolve_canonical_metrics(catalog=[_md("ghost", "")], ontology=None)
    assert res == []


# ── unified_metric_grounding — ONE block both NL2SQL paths inject (UNIFY, 2026-06-21) ──
# /chat used build_metrics_block (catalog only) while Deep used canonical_metrics_block
# (catalog + north-star + ontology), so they could disagree on the same metric. The unified
# block must surface the connection's GOVERNED north-star value_sql (what /chat was missing).
def test_unified_grounding_surfaces_north_star(monkeypatch):
    from aughor.semantic import canonical as C

    class _NSM:
        name = "Gross Margin Rate"
        value_sql = "SELECT ROUND(100.0 * SUM(margin) / NULLIF(SUM(price), 0), 2) FROM t"
        unit_or_range = "%"
        definition = "gross margin"

    class _Prof:
        north_star_metrics = [_NSM()]

    monkeypatch.setattr("aughor.profile.store.load", lambda c, s=None: _Prof())
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda *a, **k: [])  # empty catalog → no DB open
    out = C.unified_metric_grounding("conn", "schema", schema_text="TABLE: t\n  margin\n  price")
    assert "Gross Margin Rate" in out
    assert "SUM(margin)" in out  # the governed value_sql is present (chat previously never saw it)


def test_unified_grounding_noop_safe_without_connection(monkeypatch):
    from aughor.semantic import canonical as C
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda *a, **k: [])
    # no connection, no metrics → empty string, never raises
    assert C.unified_metric_grounding("", None, schema_text="") == ""


# ── resolve_contracts / render_contracts_block — the contract-native twin (REC-U10) ────────
# These use REAL models (the adapters read attributes directly, not defensively) and prove the
# contract path resolves + renders identically to the CanonicalMetric path it will replace.

def _real_md(name, sql, **kw):
    from aughor.semantic.metrics import MetricDefinition
    return MetricDefinition(name=name, label=kw.get("label", name), sql=sql,
                            unit=kw.get("unit"), caveats=kw.get("caveats"),
                            tables=kw.get("tables", []), additivity=kw.get("additivity"),
                            target_value=kw.get("target_value"))


def _real_om(mid, sql, verified=False, **kw):
    from aughor.ontology.models import OntologyMetric
    return OntologyMetric(id=mid, display_name=kw.get("display_name", mid), entity=kw.get("entity", "e"),
                          formula_sql=sql, unit=kw.get("unit", ""), tables=kw.get("tables", []),
                          verified=verified)


def _real_onto(*metrics):
    from types import SimpleNamespace
    return SimpleNamespace(metrics={m.id: m for m in metrics})


def test_resolve_contracts_render_is_byte_identical_to_canonical(monkeypatch):
    """The strongest guarantee: on the same three-source inputs, the contract render equals the
    legacy CanonicalMetric render exactly — so flipping the flag is a pure no-op on the prompt."""
    from aughor.semantic import canonical as C

    catalog = [_real_md("revenue", "SUM(price*qty)", unit="$", caveats="net of refunds")]
    onto = _real_onto(
        _real_om("aov", "SUM(amount)/COUNT(*)", verified=True, unit="$"),
        _real_om("churn", "1 - retention", verified=False),   # excluded in both by default
    )

    class _NSM:
        name = "gross_margin"
        value_sql = "SUM(margin)/NULLIF(SUM(price),0)"
        unit_or_range = "%"
        definition = "gross margin rate"

    class _Prof:
        north_star_metrics = [_NSM()]

    monkeypatch.setattr("aughor.profile.store.load", lambda c, s=None: _Prof())

    canon = C.resolve_canonical_metrics("conn", None, catalog=catalog, ontology=onto)
    contracts = C.resolve_contracts("conn", None, catalog=catalog, ontology=onto)

    # same set of keys survive dedup, same order
    assert [m.name for m in canon] == [c.key for c in contracts]
    # byte-identical rendered block, default AND include_unverified
    assert C.render_contracts_block(contracts) == C.render_canonical_metrics_block(canon)
    assert (C.render_contracts_block(contracts, include_unverified=True)
            == C.render_canonical_metrics_block(canon, include_unverified=True))
    # and it actually rendered the three authoritative sources
    block = C.render_contracts_block(contracts)
    assert "revenue [$] = SUM(price*qty)" in block
    assert "aov" in block and "gross_margin" in block
    assert "churn" not in block                          # unverified ontology excluded


def test_resolve_contracts_precedence_catalog_wins(monkeypatch):
    from aughor.semantic import canonical as C
    monkeypatch.setattr("aughor.profile.store.load", lambda c, s=None: None)
    catalog = [_real_md("revenue", "SUM(price*qty)")]
    onto = _real_onto(_real_om("revenue", "SUM(net)", verified=True))
    contracts = C.resolve_contracts("conn", None, catalog=catalog, ontology=onto)
    rev = {c.key: c for c in contracts}["revenue"]
    assert rev.source == "catalog" and rev.sql == "SUM(price*qty)"   # human catalog outranks ontology


def test_resolve_contracts_carries_rich_fields_canonical_dropped(monkeypatch):
    """The whole point of the contract: it keeps thresholds/additivity the CanonicalMetric lost."""
    from aughor.semantic import canonical as C
    monkeypatch.setattr("aughor.profile.store.load", lambda c, s=None: None)
    catalog = [_real_md("mrr", "SUM(amount)", additivity="additive", target_value=100000.0)]
    contracts = C.resolve_contracts("conn", None, catalog=catalog, ontology=None)
    c = contracts[0]
    assert c.additivity == "additive" and c.target_value == 100000.0


def test_resolve_contracts_skips_empty_sql_and_is_noop_safe(monkeypatch):
    from aughor.semantic import canonical as C
    monkeypatch.setattr("aughor.profile.store.load", lambda c, s=None: None)
    assert C.resolve_contracts("conn", None, catalog=[_real_md("ghost", "")], ontology=None) == []
    assert C.resolve_contracts("", None, catalog=[], ontology=None) == []
    assert C.render_contracts_block([]) == ""


# ── semantic.contract_live flag — flipping it is a pure no-op on the emitted prompt ────────

def _pin_three_sources(monkeypatch):
    """Fix the loaded catalog/ontology/profile so the only variable across a flag toggle is
    which resolver renders them."""
    from aughor.semantic import canonical as C
    catalog = [_real_md("revenue", "SUM(price*qty)", unit="$", caveats="net of refunds")]
    onto = _real_onto(_real_om("aov", "SUM(a)/COUNT(*)", verified=True),
                      _real_om("churn", "1 - r", verified=False))

    class _NSM:
        name = "gross_margin"
        value_sql = "SUM(m)/NULLIF(SUM(p),0)"
        unit_or_range = "%"
        definition = "gross margin rate"

    class _Prof:
        north_star_metrics = [_NSM()]

    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda *a, **k: list(catalog))
    monkeypatch.setattr("aughor.semantic.metrics.filter_metrics_to_schema", lambda m, s: list(m))
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda c, s=None: onto)
    monkeypatch.setattr("aughor.profile.store.load", lambda c, s=None: _Prof())
    return C


def test_canonical_metrics_block_flag_toggle_is_byte_identical(monkeypatch):
    C = _pin_three_sources(monkeypatch)
    monkeypatch.delenv("AUGHOR_SEMANTIC_CONTRACT_LIVE", raising=False)
    off = C.canonical_metrics_block("conn", None, schema_text="TABLE t")
    monkeypatch.setenv("AUGHOR_SEMANTIC_CONTRACT_LIVE", "1")
    on = C.canonical_metrics_block("conn", None, schema_text="TABLE t")
    assert on == off                                     # flag flip is a no-op on the block
    assert "revenue" in on and "aov" in on and "gross_margin" in on
    assert "churn" not in on                             # unverified ontology stays excluded


def test_unified_grounding_flag_toggle_is_byte_identical(monkeypatch):
    C = _pin_three_sources(monkeypatch)
    schema = "TABLE t\n  price\n  qty\n  m\n  p"
    monkeypatch.delenv("AUGHOR_SEMANTIC_CONTRACT_LIVE", raising=False)
    off = C.unified_metric_grounding("conn", None, schema_text=schema)
    monkeypatch.setenv("AUGHOR_SEMANTIC_CONTRACT_LIVE", "1")
    on = C.unified_metric_grounding("conn", None, schema_text=schema)
    assert on == off
    assert "gross_margin" in on          # north-star renders via the (flag-gated) canonical half


# ── resolve_planning_metrics — the STRUCTURED compiler resolver (REC-U10 tail) ──────────────

def test_resolve_planning_metrics_flag_toggle_is_structurally_identical(monkeypatch):
    """The semantic compiler reads `.name`/`.verified`/`.sql`/`.tables` off each metric to bind a
    named metric to SQL. Flipping `semantic.contract_live` must leave every one of those fields
    identical, so the SQL the compiler synthesizes is unchanged — and under the flag the objects
    are contract-backed (CanonicalMetric retired from the compiler's live path)."""
    from aughor.semantic.canonical import _ContractMetricView

    C = _pin_three_sources(monkeypatch)
    monkeypatch.delenv("AUGHOR_SEMANTIC_CONTRACT_LIVE", raising=False)
    off = C.resolve_planning_metrics("conn", None, schema_text="TABLE t")
    monkeypatch.setenv("AUGHOR_SEMANTIC_CONTRACT_LIVE", "1")
    on = C.resolve_planning_metrics("conn", None, schema_text="TABLE t")

    shape = lambda ms: [(m.name, m.verified, m.sql, list(m.tables or []), m.unit) for m in ms]
    assert shape(on) == shape(off)                        # every field the compiler reads is equal
    assert all(isinstance(m, _ContractMetricView) for m in on)   # ...via the one SemanticContract
    assert [m.name for m in off] == ["aov", "churn", "gross_margin", "revenue"]   # all resolved, sorted
    # the compiler's verified gate drops unverified churn downstream (render/bind time), not here
    assert {m.name: m.verified for m in off}["churn"] is False


def test_planning_view_verified_maps_to_injectable_not_raw_verified(monkeypatch):
    """The subtle correctness point: the compiler's `verified` gate must map to the contract's
    `injectable` (== legacy CanonicalMetric.verified), NOT the raw `SemanticContract.verified`
    field. A DRAFT catalog metric is authoritative-by-provenance (injectable=True) yet
    verified=False (never executed) — mapping to the wrong field would wrongly drop it."""
    from aughor.semantic import canonical as C

    monkeypatch.setattr("aughor.profile.store.load", lambda c, s=None: None)
    monkeypatch.setenv("AUGHOR_SEMANTIC_CONTRACT_LIVE", "1")
    catalog = [_real_md("revenue", "SUM(price*qty)")]     # status defaults to "draft"
    view = C.resolve_planning_metrics("conn", None, catalog=catalog, ontology=None)[0]
    assert view.name == "revenue" and view.sql == "SUM(price*qty)"
    assert view.verified is True                          # injectable by provenance, though status=draft
    # and it equals what the legacy resolver reports for the same source
    legacy = C.resolve_canonical_metrics("conn", None, catalog=catalog, ontology=None)[0]
    assert view.verified == legacy.verified
