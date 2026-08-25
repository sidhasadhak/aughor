"""Deleting a metric is destructive, and was the one verb on this router that said nothing.

Defining and editing a metric are capability-gated and audited — the create route's own
comment says defining a governed metric "leaves a trail". Deleting was neither gated nor
guarded nor recorded, and omitting `sql` removes EVERY grain sharing the name.

Measured on a live install: `data/metrics.json` went from two governed formulas to `[]`,
one of them carrying `approved_by: Finance`, and nothing anywhere recorded it. The only
reason it was noticed is that the file happens to be tracked in git. `/metrics/{name}/audit`
would have shown a metric's whole governance history with its deletion missing.
"""
from __future__ import annotations

import pytest

from aughor.govern.actions import ActionRisk, classify


def test_deleting_a_metric_is_declared_destructive():
    """Declared, not left to the unregistered-is-HIGH fail-safe: that fail-safe only
    protects a verb somebody remembered to guard, and this one was not guarded at all.

    Asserting `classify(...) is HIGH` alone would pass with no declaration whatsoever —
    the fail-safe returns HIGH for anything unknown — so the assertion that carries this
    test is MEMBERSHIP. A vacuous guard is how a premise that is itself a bug survives.
    """
    from aughor.govern.actions import _RISK

    assert "metric.delete" in _RISK, "declared, not inferred from the unknown-verb default"
    assert classify("metric.delete") is ActionRisk.HIGH
    # The sibling it matches — removing governed semantic state.
    assert classify("ontology.delete_override") is ActionRisk.HIGH
    # And the additive verbs stay auto-allowed, or authoring a metric needs approval.
    assert classify("metric.define") is ActionRisk.LOW


@pytest.fixture()
def metrics_api(monkeypatch, tmp_path):
    """The router with an isolated catalogue and governance auto-allowed."""
    from fastapi.testclient import TestClient

    from aughor.api import app
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.json"))
    return TestClient(app)


def test_the_deletion_lands_in_the_same_trail_as_every_other_transition(metrics_api, monkeypatch):
    """A trail that records approving a formula and not removing it is worse than none:
    it reads as a complete history."""
    from aughor.semantic.metrics import MetricDefinition, save_metric

    emitted: list[tuple] = []
    monkeypatch.setattr("aughor.kernel.ledger.Ledger.default",
                        lambda: type("L", (), {"emit": lambda self, k, p, **kw: emitted.append((k, p))})())
    monkeypatch.setattr("aughor.govern.guard", lambda *a, **k: None)

    save_metric(MetricDefinition(name="revenue", label="Revenue", sql="SUM(x)",
                                 owner="Revenue team", approved_by="Finance"))

    res = metrics_api.delete("/metrics/revenue")

    assert res.status_code == 200
    kinds = [k for k, _ in emitted]
    assert "metric.governance" in kinds, "the deletion has to be queryable beside the transitions"
    payload = next(p for k, p in emitted if k == "metric.governance")
    assert payload["metric"] == "revenue" and payload["action"] == "delete"
    # Read BEFORE the delete — afterwards there is nothing left to describe, and WHOSE
    # approval was discarded is the part a reader needs.
    assert payload["approved_by"] == "Finance" and payload["owner"] == "Revenue team"


def test_the_guard_is_asked_before_anything_is_removed(metrics_api, monkeypatch):
    """A guard consulted after the write is not a guard."""
    from aughor.semantic.metrics import MetricDefinition, get_metric, save_metric

    save_metric(MetricDefinition(name="aov", label="AOV", sql="AVG(x)"))

    def _refuse(action, scope):
        assert action == "metric.delete"
        raise RuntimeError("approval required")

    monkeypatch.setattr("aughor.govern.guard", _refuse)
    with pytest.raises(RuntimeError):
        metrics_api.delete("/metrics/aov")

    assert get_metric("aov") is not None, "refused, and the metric survived"
