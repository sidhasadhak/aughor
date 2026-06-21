"""Briefing honours a WORKSPACE-scoped currency override (ROADMAP follow-up).

The briefing resolved only the app-level currency — a per-workspace override applied
frontend-side but never reached the backend narrative. _profile_signals / generate_narrative
/ get_briefing now thread workspace_id into resolve_currency (override-wins over app default,
then the inferred currency_code, then USD). See aughor/knowledge/briefing.py.
"""
from aughor.knowledge import briefing as B


def test_profile_signals_threads_workspace_id_to_resolver(monkeypatch):
    seen = {}

    def _fake_resolve(code="", workspace_id=None):
        seen["code"] = code
        seen["workspace_id"] = workspace_id
        return "EUR"

    # patch the symbol resolve_currency resolves to (imported inside the function)
    monkeypatch.setattr("aughor.orgsettings.resolve_currency", _fake_resolve)
    _tokens, sym = B._profile_signals({"currency_code": "USD", "north_star_metrics": []}, "ws-123")
    assert seen["workspace_id"] == "ws-123"   # the workspace override path is reached
    assert seen["code"] == "USD"              # inferred code still passed as the fallback
    assert sym == "€"                          # EUR → € symbol


def test_profile_signals_app_level_when_no_workspace(monkeypatch):
    seen = {}

    def _fake_resolve(code="", workspace_id=None):
        seen["workspace_id"] = workspace_id
        return "USD"

    monkeypatch.setattr("aughor.orgsettings.resolve_currency", _fake_resolve)
    B._profile_signals({"currency_code": "USD"}, None)
    assert seen["workspace_id"] is None   # app-level resolution (unchanged default)
