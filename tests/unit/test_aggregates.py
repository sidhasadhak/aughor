"""Phase 7 of the 2027 study, P7-5 — aggregate priors across installs (`aughor/packs/aggregates.py`)
behind the off-by-default flag `aggregates.share`.

What these hold: the aggregate carries pack records, base rates, normal ranges and method backtests
and never a connection id, a claim's text or an absolute value of a metric that is not a share; a
document that would is refused; with the flag off nothing leaves — the export door refuses and says
why — and with it on the same document is handed out marked shareable.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from aughor.packs import aggregates as AG
from aughor.record import claims as C
from aughor.record import scenario as S
from aughor.routers import ledger as R


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _scored(conn: str, metric: str, unit: str, low: float, high: float, actual: float):
    proj = S.Projection(method="history", value=(low + high) / 2, low=low, high=high, coverage=0.8, unit=unit, backtest={"n": 6})
    pid = S.predict(metric=metric, projection=proj, settles_on="2026-10-01", author="system", connection_id=conn)
    S.score_prediction(C.get(pid), actual=actual, measured_on="2026-10-02")


def test_the_aggregate_never_carries_a_customers_data_and_the_rule_is_enforced():
    conn = _conn()
    _scored(conn, "margin_share", "ratio", 2.0, 6.0, 4.0)
    _scored(conn, "margin_share", "ratio", 3.0, 7.0, 9.0)
    _scored(conn, "revenue_total", "EUR", 90.0, 110.0, 100.0)
    doc = AG.compute()
    assert doc["version"] == "2027.1" and len(doc["install"]) == 12 and "a connection id" in doc["never_includes"]
    share = next(r for r in doc["normal_ranges"] if r["metric"] == "margin_share")
    assert share["n"] == 2 and share["coverage_observed"] == 0.5 and share["band"] == {"low": 2.0, "high": 7.0, "note": "a share; the band itself"}
    money = next(r for r in doc["normal_ranges"] if r["metric"] == "revenue_total")
    assert "band" not in money and money["relative_width"] == pytest.approx(0.2) and money["note"].startswith("not a share")
    assert "%" not in AG.SHARE_UNITS  # the Record's `%` is a relative band, a change — never a level
    assert conn not in str(doc)
    with pytest.raises(ValueError, match="never names a customer's data"):
        AG.assert_no_identifiers({"normal_ranges": [{"metric": "x", "connection_id": conn}]})
    with pytest.raises(ValueError):
        AG.assert_no_identifiers({"packs": [{"claims": {"text": "Orders were 1,200"}}]})


def test_nothing_leaves_until_a_person_turns_sharing_on(monkeypatch):
    from aughor.kernel.flags import FLAG_ENV, clear_flag, flag_disposition
    assert FLAG_ENV["aggregates.share"] == "AUGHOR_AGGREGATES_SHARE" and flag_disposition("aggregates.share") == "experiment"
    clear_flag("aggregates.share")
    monkeypatch.delenv("AUGHOR_AGGREGATES_SHARE", raising=False)
    assert AG.sharing_enabled() is False
    with pytest.raises(PermissionError, match="the user's call"):
        AG.export()
    with pytest.raises(HTTPException) as e:
        R.export_aggregates()
    assert e.value.status_code == 403 and "nothing leaves" in e.value.detail
    local = R.read_aggregates()
    assert local["sharing"] is False and local["flag"] == "aggregates.share" and "normal_ranges" in local
    monkeypatch.setenv("AUGHOR_AGGREGATES_SHARE", "1")
    assert AG.sharing_enabled() is True
    out = R.export_aggregates()
    assert out["shareable"] is True and "install" in out and "never_includes" in out
