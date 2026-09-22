"""CB-6 — what the company is trying to do this quarter (Arc CB, 2026-09-23).

Measured before this wave: the platform stored nothing about what the organisation is working on
now; the Briefing ranked a finding by the size of its move and whether it touched an INFERRED
north-star metric, never by whether it bore on a goal leadership had set. Now people write a short
list of priorities in organisation settings (never inferred — §6 item 20's rule), triage counts a
finding that bears on one, and the brief's citation says which goal it bears on.
"""
from __future__ import annotations

from aughor.knowledge.triage import impact_score, north_star_tokens, priority_hit, priority_tokensets
from aughor.orgsettings.models import OrgSettings, Priority

PRIORITIES = [{"metric": "return rate", "target": "< 8%", "direction": "down", "by": "Q4"},
              {"metric": "net revenue", "target": "£1.2M", "direction": "up"}]


class TestPeopleWriteThem:
    def test_the_settings_carry_priorities_and_default_to_none(self):
        assert OrgSettings().priorities == []
        s = OrgSettings(priorities=[Priority(metric="return rate", target="< 8%", direction="down", by="Q4")])
        assert s.model_dump()["priorities"][0] == {"metric": "return rate", "target": "< 8%", "direction": "down", "by": "Q4", "note": ""}

    def test_a_workspace_with_no_priorities_inherits_the_organisations(self, monkeypatch):
        from aughor.orgsettings import store as S
        from types import SimpleNamespace
        monkeypatch.setattr(S, "load_org_settings", lambda: OrgSettings(priorities=[Priority(metric="return rate")]))
        monkeypatch.setattr("aughor.workspace.store.get_workspace", lambda wid: SimpleNamespace(settings_override={"priorities": [], "currency_code": "EUR"}))
        eff = S.effective_settings("ws1")
        assert [p.metric for p in eff.priorities] == ["return rate"] and eff.currency_code == "EUR"


class TestTriageCountsThem:
    def test_a_finding_that_bears_on_a_priority_outranks_one_that_does_not(self):
        toks = priority_tokensets(PRIORITIES)
        on_goal = impact_score("Return rate rose from 6.1% to 9.4% in September", 3, 0.8, [], priority_tokensets=toks)
        off_goal = impact_score("Basket size rose from 6.1% to 9.4% in September", 3, 0.8, [], priority_tokensets=toks)
        assert on_goal > off_goal and round(on_goal - off_goal, 4) == 0.30
        assert impact_score("Return rate rose 9%", 3, 0.8, []) == impact_score("Return rate rose 9%", 3, 0.8, [], priority_tokensets=[])

    def test_the_goal_a_finding_bears_on_is_named_with_the_north_star_word_rule(self):
        assert priority_hit("Return rate rose to 9.4%", PRIORITIES) == "return rate"
        assert priority_hit("Net revenue fell 4% week on week", PRIORITIES) == "net revenue"
        assert priority_hit("New-customer orders rose", PRIORITIES) == ""        # neither goal
        assert priority_hit("Revenue fell", [{"metric": "average order value"}]) == ""   # one token of a two-token name is not a hit
        assert priority_tokensets([]) == [] and north_star_tokens(["return rate"]) == priority_tokensets([{"metric": "return rate"}])


class TestTheBriefSaysWhichGoal:
    def test_the_citation_carries_the_goal_and_the_narrator_sees_the_priorities(self, monkeypatch):
        from aughor.knowledge import briefing as B
        from types import SimpleNamespace
        seen = {}

        class _Prov:
            def complete(self, system, user, response_model, **kw):
                seen["user"] = user
                return SimpleNamespace(narrative="Return rate rose to 9.4% [1].", headline_theme="Returns",
                                       citations=[SimpleNamespace(ref="1", insight_id="i1", domain="ops", angle="returns", finding="")])
        monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role: _Prov())
        monkeypatch.setattr("aughor.orgsettings.effective_settings",
                            lambda wid=None: OrgSettings(priorities=[Priority(metric="return rate", target="< 8%", direction="down", by="Q4")]))
        monkeypatch.setattr(B, "update_dossier", lambda *a, **k: None, raising=False)
        out = B.generate_narrative({"ops": [{"id": "i1", "finding": "Return rate rose from 6.1% to 9.4% in September",
                                             "novelty": 3, "confidence": 0.8, "angle": "returns", "sql": "SELECT 1"}]},
                                   [], "c1")
        assert out["citations"][0]["priority"] == "return rate"
        assert "DECLARED PRIORITIES THIS QUARTER" in seen["user"] and "return rate, target < 8%, down is good, by Q4" in seen["user"]
