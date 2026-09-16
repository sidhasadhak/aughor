"""B-8 — metric governance lifecycle state machine + back-compat defaults.

Pins the transitions (draft→proposed→approved→deprecated), the stamps/version bumps,
the illegal-transition guards, and the audit record each transition produces.
"""
import pytest

from aughor.semantic.governance import apply_transition, can_transition
from aughor.semantic.metrics import MetricDefinition

NOW = "2026-06-13T12:00:00+00:00"


def _draft():
    return {"name": "mrr", "label": "MRR", "sql": "SUM(amount)", "status": "draft", "version": 0}


class TestHappyPath:
    def test_propose_then_approve(self):
        m, a1 = apply_transition(_draft(), "propose", "Alice", NOW)
        assert m["status"] == "proposed" and m["proposed_by"] == "Alice" and m["proposed_at"] == NOW
        assert a1 == {"metric": "mrr", "action": "propose", "actor": "Alice",
                      "from": "draft", "to": "proposed", "version": 0, "at": NOW}
        m, a2 = apply_transition(m, "approve", "Finance", NOW)
        assert m["status"] == "approved" and m["approved_by"] == "Finance" and m["approved_at"] == NOW
        assert m["version"] == 1                       # 0 → 1 on first approval
        assert a2["action"] == "approve" and a2["from"] == "proposed" and a2["version"] == 1

    def test_reject_returns_to_draft(self):
        m, _ = apply_transition(_draft(), "propose", "Alice", NOW)
        m, a = apply_transition(m, "reject", "Finance", NOW)
        assert m["status"] == "draft" and a["to"] == "draft"

    def test_deprecate_and_repropose(self):
        m = {"name": "mrr", "label": "MRR", "sql": "SUM(amount)", "status": "approved", "version": 1}
        m, _ = apply_transition(m, "deprecate", "Finance", NOW)
        assert m["status"] == "deprecated"
        m, _ = apply_transition(m, "propose", "Alice", NOW)   # deprecated → proposed
        assert m["status"] == "proposed"

    def test_version_bumps_on_reapproval(self):
        approved = {"name": "mrr", "label": "MRR", "sql": "SUM(amount)",
                    "status": "proposed", "version": 1}   # was approved once, now re-proposed
        m, a = apply_transition(approved, "approve", "Finance", NOW)
        assert m["version"] == 2 and a["version"] == 2


class TestIllegalTransitions:
    def test_cannot_approve_a_draft(self):
        with pytest.raises(ValueError, match="cannot 'approve'"):
            apply_transition(_draft(), "approve", "Finance", NOW)

    def test_cannot_approve_twice(self):
        approved = {"name": "x", "label": "X", "sql": "1", "status": "approved", "version": 1}
        with pytest.raises(ValueError, match="cannot 'approve'"):
            apply_transition(approved, "approve", "Finance", NOW)

    def test_unknown_action_raises(self):
        with pytest.raises(ValueError, match="unknown governance action"):
            apply_transition(_draft(), "yeet", "Alice", NOW)

    def test_blank_actor_raises(self):
        with pytest.raises(ValueError, match="actor is required"):
            apply_transition(_draft(), "propose", "  ", NOW)

    def test_purity_input_not_mutated(self):
        d = _draft()
        apply_transition(d, "propose", "Alice", NOW)
        assert d["status"] == "draft"   # original dict untouched


class TestCanTransition:
    def test_matrix(self):
        assert can_transition("draft", "propose") is True
        assert can_transition("draft", "approve") is False
        assert can_transition("proposed", "approve") is True
        assert can_transition("approved", "deprecate") is True
        assert can_transition(None, "propose") is True   # None ⇒ draft
        assert can_transition("approved", "nonsense") is False


class TestBackCompatDefaults:
    def test_legacy_approved_metric_defaults_to_approved_v1(self):
        m = MetricDefinition(name="revenue", label="Revenue", sql="SUM(total_amount)", approved_by="Finance")
        assert m.status == "approved" and m.version == 1

    def test_new_metric_defaults_to_draft_v0(self):
        m = MetricDefinition(name="x", label="X", sql="SUM(y)")
        assert m.status == "draft" and m.version == 0

    def test_explicit_status_is_respected(self):
        m = MetricDefinition(name="x", label="X", sql="1", status="proposed")
        assert m.status == "proposed"


class TestValidateMetricRunsForReal:
    """HB-2 found the tie-out door broken twice over: the module called
    ``conn.execute(sql)`` against the governed ``execute(hypothesis_id, sql)``
    signature (every test errored), and a stringified boolean ``'False'`` read as
    truthy (a failing test could not fail). The departure gate is the first caller
    that needs the verdict to be RIGHT, so both defects get direct coverage."""

    def _metric(self):
        return MetricDefinition(
            name="revenue", label="Revenue", sql="SUM(total_amount)",
            quality_tests=["SELECT COUNT(*) = 0 FROM orders WHERE total_amount IS NULL"])

    def test_governed_two_arg_connection_is_called_correctly(self):
        from types import SimpleNamespace
        from aughor.semantic.metrics import validate_metric
        calls = []

        class _Conn:
            def execute_bounded(self, label, sql, max_rows):
                calls.append((label, sql, max_rows))
                return SimpleNamespace(rows=[["True"]])
        v = validate_metric(self._metric(), _Conn())
        assert v.passed is True
        assert calls and calls[0][0] == "__metric_tieout__"

    def test_stringified_false_fails_the_test(self):
        from types import SimpleNamespace
        from aughor.semantic.metrics import validate_metric

        class _Conn:
            def execute_bounded(self, label, sql, max_rows):
                return SimpleNamespace(rows=[["False"]])
        v = validate_metric(self._metric(), _Conn())
        assert v.passed is False

    def test_raw_single_arg_connection_still_works(self):
        from types import SimpleNamespace
        from aughor.semantic.metrics import validate_metric

        class _Raw:
            def execute(self, sql):
                return SimpleNamespace(rows=[[1]])
        v = validate_metric(self._metric(), _Raw())
        assert v.passed is True
