"""The usage read prices its calls only after the provider's catalogue was asked (`routers.governance.get_usage`).

Measured 2026-10-12 on a freshly restarted API: Spend read "$0.00 at least" — `GET /usage` priced every call before
anything had loaded the catalogue's rates (only the obs summary asked), then $0.95 once something else did. The reader
now asks first, at most hourly, as the obs summary does; an unreachable catalogue still leaves its models `unpriced`.
"""
from __future__ import annotations

from aughor.obs import usage
from aughor.routers import governance


def test_the_catalogue_is_asked_before_the_calls_are_priced(monkeypatch):
    said: list[str] = []
    monkeypatch.setattr(usage, "ensure_catalogue_prices", lambda **k: said.append("prices") or 3)

    class _Report:
        def to_dict(self):
            return {"rows": []}

    monkeypatch.setattr(usage, "usage_report", lambda **k: said.append("priced") or _Report())
    assert governance.get_usage(by="provider,model", scan=10, org_id=None) == {"rows": []}
    assert said == ["prices", "priced"]
