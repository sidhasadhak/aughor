"""Declarative metric additivity (ROADMAP follow-up).

A MetricDefinition can DECLARE `additivity`; it overrides the SQL inference (the same
gate the answer-summary concentration check uses). Surfaced in the metrics-catalog prompt
so the generator never sums / shares-of-total a ratio metric. See aughor/semantic/metrics.py.
"""
from aughor.semantic import metrics as M


def _m(sql, additivity=None, name="m"):
    return M.MetricDefinition(name=name, label=name, sql=sql, tables=["t"], additivity=additivity)


def test_declared_additivity_overrides_inference_both_ways():
    assert M.metric_additivity(_m("AVG(z)", additivity="additive")) is True       # override an AVG → additive
    assert M.metric_additivity(_m("SUM(z)", additivity="non_additive")) is False  # override a SUM → non-additive
    assert M.metric_additivity(_m("SUM(z)", additivity="non-additive")) is False  # hyphen tolerated


def test_inference_used_when_undeclared():
    assert M.metric_additivity(_m("SUM(z)", name="revenue")) is True
    assert M.metric_additivity(_m("ROUND(AVG(z), 2)", name="aov")) is False


def test_non_additive_metric_is_tagged_in_block(monkeypatch):
    monkeypatch.setattr(M, "list_metrics", lambda *a, **k: [_m("ROUND(AVG(z), 2)", name="aov")])
    out = M.build_metrics_block(schema_text="TABLE: t\n  z  DOUBLE\n", connection_id="")
    assert "non-additive" in out and "share-of-total" in out


def test_additive_metric_not_tagged(monkeypatch):
    monkeypatch.setattr(M, "list_metrics", lambda *a, **k: [_m("SUM(z)", name="revenue", additivity="additive")])
    out = M.build_metrics_block(schema_text="TABLE: t\n  z  DOUBLE\n", connection_id="")
    assert "non-additive" not in out
