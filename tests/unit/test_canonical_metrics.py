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
