"""Follow-up A — reconcile the WHERE/WHY/WHEN lens grain.

A cross-sectional "why is the rate high" run can compute the SAME rate at two grains across its
concurrent lenses — per order (~40%) vs per line-item (~76%) — so one report contradicts itself.
The metric's own table (intake `metric_table`) is the canonical unit; the multi-lens node derives it
once and hands the SAME grain to the WHERE rate scan and the WHEN trend, and each labels its number
with that unit. These tests pin the derivation, the plan directive + summary tag, and the threading.
"""
from __future__ import annotations

import aughor.agent.investigate as inv


# ── _canonical_grain ─────────────────────────────────────────────────────────────

def test_canonical_grain_labels_by_metric_table():
    assert inv._canonical_grain({"metric_table": "shop.order_items"})["label"] == "line item"
    assert inv._canonical_grain({"metric_table": "shop.line_items"})["label"] == "line item"
    assert inv._canonical_grain({"metric_table": "shop.orders"})["label"] == "order"
    assert inv._canonical_grain({"metric_table": "shop.returns"})["label"] == "return"
    assert inv._canonical_grain({"metric_table": "db.customers"})["label"] == "customer"
    # Table is carried through qualified (the denominator references it verbatim).
    assert inv._canonical_grain({"metric_table": "shop.order_items"})["table"] == "shop.order_items"


def test_canonical_grain_none_without_metric_table():
    assert inv._canonical_grain({}) is None
    assert inv._canonical_grain({"metric_table": ""}) is None


# ── directive + tag ──────────────────────────────────────────────────────────────

def test_grain_plan_directive_pins_the_denominator():
    d = inv._grain_plan_directive({"table": "shop.order_items", "label": "line item"})
    assert "shop.order_items" in d
    assert "line item" in d
    assert "do NOT collapse" in d           # forbids silently coarsening the grain
    assert inv._grain_plan_directive(None) == ""


def test_grain_summary_tag_format():
    assert inv._grain_summary_tag({"label": "line item"}) == "[per line item]"
    assert inv._grain_summary_tag(None) == ""
    assert inv._grain_summary_tag({}) == ""


# ── the real ada_cross_section injects the directive + tags the summary ───────────

def test_rate_lens_injects_grain_directive_and_tags_summary(monkeypatch):
    captured = {}

    def fake_run(conn, **kw):
        captured["plan_user"] = kw.get("plan_user", "")
        return inv._PhaseRun(ok=True, results=[], results_text="", interpretation=None)

    monkeypatch.setattr(inv, "run_analysis_phase", fake_run)
    state = {"question": "why are returns so high?", "schema_context": "TABLE: shop.order_items",
             "investigation_phases": [],
             "_ada_intake": {"metric_table": "shop.order_items", "metric_label": "return rate",
                             "metric_sql": "AVG(is_returned)*100", "dimensions": ["shop.order_items.brand"]}}
    grain = inv._canonical_grain(state["_ada_intake"])

    out = inv.ada_cross_section(state, object(), grain=grain)
    # The plan the coder receives pins the grain…
    assert "GRAIN (measure consistently" in captured["plan_user"]
    assert "shop.order_items" in captured["plan_user"]
    # …and the emitted phase summary is tagged with the unit.
    assert out["_cross_section_summary"].startswith("[per line item]")


def test_rate_lens_byte_identical_without_grain(monkeypatch):
    captured = {}

    def fake_run(conn, **kw):
        captured["plan_user"] = kw.get("plan_user", "")
        return inv._PhaseRun(ok=True, results=[], results_text="", interpretation=None)

    monkeypatch.setattr(inv, "run_analysis_phase", fake_run)
    state = {"question": "q", "schema_context": "TABLE: shop.orders", "investigation_phases": [],
             "_ada_intake": {"metric_table": "shop.orders", "metric_label": "m",
                             "metric_sql": "SUM(x)", "dimensions": ["shop.orders.channel"]}}

    out = inv.ada_cross_section(state, object())        # no grain → default path
    assert "GRAIN (measure consistently" not in captured["plan_user"]
    assert not out["_cross_section_summary"].startswith("[per ")


# ── the multi-lens node hands the SAME grain to WHERE and WHEN ─────────────────────

class _FakeConn:
    def make_reader(self):
        return _FakeConn()


def test_multilens_threads_one_grain_to_where_and_when(monkeypatch):
    seen = {}

    def xsec(state, conn, *, dims_override=None, phase_meta=None, period_directive=None,
             extra_dims=None, extra_schema=None, extra_directive=None, grain=None):
        seen["where_grain"] = grain
        pid = (phase_meta or ("cross_section", "X", "🧭"))[0]
        base = state.get("investigation_phases", [])
        return {"investigation_phases": base + [{"phase_id": pid}], "_cross_section_summary": "s"}

    def when(state, conn, axis, grain=None):
        seen["when_grain"] = grain
        return {"phase_id": "temporal_when"}, None

    monkeypatch.setattr(inv, "ada_cross_section", xsec)
    monkeypatch.setattr(inv, "_run_composition_lens", lambda s, c, dims: {"phase_id": "cross_section_mechanism"})
    monkeypatch.setattr(inv, "_run_temporal_lens", when)
    monkeypatch.setattr(inv, "_resolve_temporal_axis",
                        lambda s, c=None, intake_data=None: {"date_column": "shop.orders.order_date"})

    state = {"schema_context": "x", "investigation_phases": [],
             "_ada_intake": {"metric_table": "shop.order_items",
                             "dimensions": ["shop.order_items.brand", "shop.returns.reason"]}}
    inv.ada_cross_section_multilens(state, _FakeConn())

    # BOTH lenses received a grain, and it is the SAME canonical unit (per line item).
    assert seen["where_grain"] == {"table": "shop.order_items", "label": "line item"}
    assert seen["when_grain"] == seen["where_grain"]
