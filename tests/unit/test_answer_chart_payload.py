"""Phase 3 — a persisted answer keeps its chart's INTENT, not just its type.

Measured 2026-08-21 against the live ledger: of 700 stored ``chat_answer`` artifacts, 700
carried ``chart_type`` and **zero** carried ``chart_config``. The exhibit spec is computed
per answer (``investigations.py`` merges ``quick_exhibit`` into ``answer.chart_config``),
reaches the browser, and was then dropped at the write — so the chart a reader was actually
shown could not be reconstructed from the ledger afterwards.
"""

from aughor.agent.chart_vocab import answer_chart_payload


def test_chart_config_survives_the_write():
    cfg = {"x_field": "region", "y_field": "revenue",
           "exhibit": {"color": {"mode": "severity"}, "ref_lines": [{"value": 10, "label": "target"}]}}
    out = answer_chart_payload("bar_horizontal", cfg, 42, "quick")
    assert out["chart_config"] == cfg, "the config the browser rendered must reach the ledger"
    assert out["chart_config"]["exhibit"]["color"]["mode"] == "severity"
    assert out["chart_type"] == "bar_horizontal"
    assert out["row_count"] == 42
    assert out["complexity_tier"] == "quick"


def test_an_empty_config_adds_nothing():
    # Absent-means-default: an answer with no exhibit must not write {"exhibit": None},
    # which would read as a real config to anything checking for the key.
    out = answer_chart_payload("bar", {"exhibit": None}, 7, None)
    assert "chart_config" not in out
    assert "complexity_tier" not in out
    assert out == {"row_count": 7, "chart_type": "bar"}


def test_it_records_intent_and_never_data():
    # The intent is small and safe to keep. Rows are NOT: persisting them is a storage and
    # data-retention decision, deliberately not taken here.
    out = answer_chart_payload("line", {"x_field": "day", "rows": [[1, 2]], "columns": ["a"]}, 3, None)
    assert "rows" in out["chart_config"], "the helper does not filter caller keys..."
    # ...so the guarantee lives at the call site: it is handed answer.chart_config, which
    # carries field names and the exhibit, never the result set.
    assert answer_chart_payload("line", None, 3, None) == {"row_count": 3, "chart_type": "line"}


def test_a_chartless_answer_still_records_its_size():
    assert answer_chart_payload(None, None, 0, None) == {"row_count": 0}
