"""Governed-metric resolution — precedence + injection safety, contract-native.

Ensures "revenue" resolves to ONE formula across stores so /chat and ADA can't
diverge. The legacy CanonicalMetric resolver was DELETED by flag endgame Wave 2
(2026-08-06) after the `semantic.contract_live` migration soaked default-ON with a
byte-identical-render proof (receipt e801ff3a4448); these tests carry the durable
claims forward onto the surviving resolver (`resolve_contracts` /
`resolve_planning_metrics` / `render_contracts_block`). The old flag-toggle
equivalence tests retired with their oracle — equivalence to a deleted path is not
a property of the live system.

See aughor/semantic/canonical.py + aughor/semantic/contracts.py.
"""
from types import SimpleNamespace


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
    return SimpleNamespace(metrics={m.id: m for m in metrics})


def _no_profile(monkeypatch):
    monkeypatch.setattr("aughor.business_profile.store.load", lambda c, s=None: None)


# ── precedence + dedup (the "one formula" guarantee) ──────────────────────────

def test_catalog_outranks_ontology(monkeypatch):
    from aughor.semantic import canonical as C
    _no_profile(monkeypatch)
    catalog = [_real_md("revenue", "SUM(price*qty)")]
    onto = _real_onto(_real_om("revenue", "SUM(invoices.revenue_net)", verified=True))
    rev = {c.key: c for c in C.resolve_contracts("conn", None, catalog=catalog, ontology=onto)}["revenue"]
    assert rev.sql == "SUM(price*qty)"          # curated catalog wins
    assert rev.source == "catalog"


def test_dedup_by_normalized_key(monkeypatch):
    from aughor.semantic import canonical as C
    _no_profile(monkeypatch)
    catalog = [_real_md("Net Revenue", "SUM(net)")]
    onto = _real_onto(_real_om("net_revenue", "SUM(gross)", verified=True))
    res = C.resolve_contracts("conn", None, catalog=catalog, ontology=onto)
    assert len(res) == 1, [c.key for c in res]  # "Net Revenue" and "net_revenue" collapse
    assert res[0].sql == "SUM(net)"             # catalog precedence


def test_ontology_verified_flag_drives_source_and_injectability(monkeypatch):
    from aughor.semantic import canonical as C
    _no_profile(monkeypatch)
    onto = _real_onto(
        _real_om("aov", "SUM(amount)/COUNT(DISTINCT order_id)", verified=True),
        _real_om("margin", "SUM(profit)/SUM(revenue)", verified=False),
    )
    res = {c.key: c for c in C.resolve_contracts("conn", None, catalog=[], ontology=onto)}
    # The contract keys provenance as source="ontology" + a verified bit (the legacy
    # shape fused them into ontology_verified/_unverified); injectability derives.
    assert res["aov"].source == "ontology" and res["aov"].verified and res["aov"].injectable
    assert res["margin"].source == "ontology" and not res["margin"].injectable
    block = C.render_contracts_block(list(res.values()))
    assert "aov" in block            # verified → injected
    assert "margin" not in block     # unverified → excluded


# ── render policy ─────────────────────────────────────────────────────────────

def test_render_excludes_unverified_by_default(monkeypatch):
    from aughor.semantic import canonical as C
    _no_profile(monkeypatch)
    onto = _real_onto(_real_om("churn", "1 - retention", verified=False))
    res = C.resolve_contracts("conn", None, catalog=[], ontology=onto)
    assert C.render_contracts_block(res) == ""   # unverified not injected as authoritative
    block = C.render_contracts_block(res, include_unverified=True)
    assert "churn" in block and "unverified" in block


def test_render_lists_verified_with_exact_formula(monkeypatch):
    from aughor.semantic import canonical as C
    _no_profile(monkeypatch)
    catalog = [_real_md("revenue", "SUM(price*qty)", unit="$")]
    res = C.resolve_contracts("conn", None, catalog=catalog, ontology=None)
    block = C.render_contracts_block(res)
    assert "revenue [$] = SUM(price*qty)" in block
    assert "use these EXACT formulas" in block


def test_empty_and_missing_sql_are_noop_safe(monkeypatch):
    from aughor.semantic import canonical as C
    _no_profile(monkeypatch)
    assert C.resolve_contracts("conn", None, catalog=[_real_md("ghost", "")], ontology=None) == []
    assert C.resolve_contracts("", None, catalog=[], ontology=None) == []
    assert C.render_contracts_block([]) == ""


def test_contracts_carry_rich_fields_the_legacy_shape_dropped(monkeypatch):
    """The point of the migration: thresholds/additivity survive resolution."""
    from aughor.semantic import canonical as C
    _no_profile(monkeypatch)
    catalog = [_real_md("mrr", "SUM(amount)", additivity="additive", target_value=100000.0)]
    c = C.resolve_contracts("conn", None, catalog=catalog, ontology=None)[0]
    assert c.additivity == "additive" and c.target_value == 100000.0


# ── unified_metric_grounding — ONE block both NL2SQL paths inject ─────────────

def test_unified_grounding_surfaces_north_star(monkeypatch):
    from aughor.semantic import canonical as C

    class _NSM:
        name = "Gross Margin Rate"
        value_sql = "SELECT ROUND(100.0 * SUM(margin) / NULLIF(SUM(price), 0), 2) FROM t"
        unit_or_range = "%"
        definition = "gross margin"

    class _Prof:
        north_star_metrics = [_NSM()]

    monkeypatch.setattr("aughor.business_profile.store.load", lambda c, s=None: _Prof())
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda *a, **k: [])
    out = C.unified_metric_grounding("conn", "schema", schema_text="TABLE: t\n  margin\n  price")
    assert "Gross Margin Rate" in out
    assert "SUM(margin)" in out  # the governed value_sql is present (chat previously never saw it)


def test_unified_grounding_noop_safe_without_connection(monkeypatch):
    from aughor.semantic import canonical as C
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda *a, **k: [])
    assert C.unified_metric_grounding("", None, schema_text="") == ""


# ── resolve_planning_metrics — the STRUCTURED compiler resolver ───────────────

def test_planning_metrics_are_contract_backed_views(monkeypatch):
    """The compiler reads `.name`/`.verified`/`.sql`/`.tables`/`.unit` off each metric.
    They must arrive via `_ContractMetricView` over the one SemanticContract — the
    shape the deleted CanonicalMetric list carried, now with a single source of truth."""
    from aughor.semantic import canonical as C
    from aughor.semantic.canonical import _ContractMetricView
    _no_profile(monkeypatch)
    catalog = [_real_md("revenue", "SUM(price*qty)", unit="$")]
    onto = _real_onto(_real_om("aov", "SUM(a)/COUNT(*)", verified=True),
                      _real_om("churn", "1 - r", verified=False))
    ms = C.resolve_planning_metrics("conn", None, catalog=catalog, ontology=onto)
    assert all(isinstance(m, _ContractMetricView) for m in ms)
    shape = {m.name: (m.verified, m.sql) for m in ms}
    assert shape["revenue"] == (True, "SUM(price*qty)")
    assert shape["churn"][0] is False    # unverified flows through; render/bind gates drop it


def test_planning_view_verified_maps_to_injectable_not_raw_verified(monkeypatch):
    """The subtle correctness point: the compiler's `verified` gate maps to the
    contract's `injectable` (the authoritative-by-provenance policy), NOT the raw
    `SemanticContract.verified` execution bit. A DRAFT catalog metric is
    injectable=True yet verified=False (never executed) — mapping to the wrong
    field would wrongly drop it from planning."""
    from aughor.semantic import canonical as C
    _no_profile(monkeypatch)
    catalog = [_real_md("revenue", "SUM(price*qty)")]     # status defaults to "draft"
    view = C.resolve_planning_metrics("conn", None, catalog=catalog, ontology=None)[0]
    assert view.name == "revenue" and view.sql == "SUM(price*qty)"
    assert view.verified is True                          # injectable by provenance
    raw = C.resolve_contracts("conn", None, catalog=catalog, ontology=None)[0]
    assert raw.injectable is True and view.verified == raw.injectable
