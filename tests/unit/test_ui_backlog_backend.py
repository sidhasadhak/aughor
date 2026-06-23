"""Backend for the UI-backlog increments: the runtime feature-flag store (P3) and the
post-processing transform endpoint (U8)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from aughor.kernel.flags import clear_flag, flag_enabled, list_flags, set_flag
from aughor.routers.query import _PostprocRequest, query_postproc


class TestFeatureFlags:
    def test_override_wins_then_env_fallback(self, monkeypatch):
        monkeypatch.delenv("AUGHOR_AI_SQL", raising=False)
        clear_flag("ai_sql")
        assert flag_enabled("ai_sql") is False          # no override, env unset
        set_flag("ai_sql", True)
        assert flag_enabled("ai_sql") is True            # runtime override wins
        set_flag("ai_sql", False)
        monkeypatch.setenv("AUGHOR_AI_SQL", "1")
        assert flag_enabled("ai_sql") is False           # override still wins over env
        clear_flag("ai_sql")
        assert flag_enabled("ai_sql") is True             # cleared → env decides
        monkeypatch.delenv("AUGHOR_AI_SQL", raising=False)
        clear_flag("ai_sql")

    def test_list_flags_shape(self):
        f = list_flags()
        assert "ai_sql" in f and "snapshot_receipts" in f
        assert {"value", "source", "env_var", "label", "description"} <= set(f["ai_sql"])


class TestPostprocEndpoint:
    def test_period_over_period_appends_column(self):
        out = query_postproc(_PostprocRequest(
            columns=["month", "revenue"], rows=[["jan", 100], ["feb", 150], ["mar", 120]],
            op="pop", value_col="revenue"))
        assert out["columns"] == ["month", "revenue", "revenue_pct_change"]
        assert out["rows"][1][-1] == 0.5 and out["rows"][2][-1] == pytest.approx(-0.2)

    def test_cumulative_and_rolling(self):
        cum = query_postproc(_PostprocRequest(columns=["m", "v"], rows=[["a", 1], ["b", 2], ["c", 3]],
                                              op="cumulative", value_col="v"))
        assert [r[-1] for r in cum["rows"]] == [1.0, 3.0, 6.0]
        roll = query_postproc(_PostprocRequest(columns=["m", "v"], rows=[["a", 2], ["b", 4], ["c", 6]],
                                               op="rolling", value_col="v", window=2))
        assert roll["rows"][1][-1] == 3.0   # mean(2,4)

    def test_contribution_refused_on_non_additive(self):
        with pytest.raises(HTTPException) as e:
            query_postproc(_PostprocRequest(columns=["seg", "aov"], rows=[["a", 69], ["b", 72]],
                                            op="contribution", value_col="aov"))
        assert e.value.status_code == 422

    def test_unknown_value_col_is_400(self):
        with pytest.raises(HTTPException) as e:
            query_postproc(_PostprocRequest(columns=["m", "v"], rows=[["a", 1]], op="pop", value_col="ghost"))
        assert e.value.status_code == 400
