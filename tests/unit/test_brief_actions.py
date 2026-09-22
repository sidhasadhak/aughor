"""CB-7 — one action beside each Briefing item (Arc CB, 2026-09-23).

Measured before this wave: the Briefing ranked findings by business impact and stopped; nothing in
its code offered an action, and recommendations with an Execute button lived a screen away in the
inbox. Now each cited item carries the single best action, chosen where the platform already keeps
its judgement: the cited investigation's own first recommendation (executable through the inbox's
gated door), else the playbook's best play by learned success rate (a suggestion, not fired). An
item with neither carries none — honest over invented.
"""
from __future__ import annotations

from types import SimpleNamespace

from aughor.knowledge.briefing import best_action_for


def _play(pid="p1", rec="Pause the two lowest-margin carriers", rate=0.8):
    return SimpleNamespace(id=pid, recommendation=rec, trigger_metric="return_rate", trigger_condition="above target",
                           historical_success_rate=rate)


class TestTheBestAction:
    def test_the_playbooks_best_play_by_learned_rate_when_no_investigation(self, monkeypatch):
        calls = {}

        def retrieve(labels, limit=6, *, learned_rates=True, industry=None, **k):
            calls.update(labels=labels, learned_rates=learned_rates, industry=industry, limit=limit)
            return [_play()]
        monkeypatch.setattr("aughor.playbook.retriever.retrieve_for_metric_and_phases", retrieve)
        a = best_action_for({"angle": "returns", "domain": "ops", "_priority": "return rate"}, industry="retail")
        assert a == {"kind": "play", "id": "p1", "text": "Pause the two lowest-margin carriers", "when": "return_rate above target",
                     "success_rate": 0.8, "executable": False, "why": "the playbook's best play for this finding, by learned success rate"}
        assert calls == {"labels": ["return rate", "returns", "ops"], "learned_rates": True, "industry": "retail", "limit": 1}

    def test_the_investigations_own_first_recommendation_wins_and_is_executable(self, monkeypatch):
        monkeypatch.setattr("aughor.db.history.get_investigation",
                            lambda inv_id: {"id": inv_id, "report": {"recommendations": [{"text": "Move the cut-off to 14:00"}]}})
        a = best_action_for({"investigation_id": "inv9", "angle": "dispatch"})
        assert a["kind"] == "recommendation" and a["inv_id"] == "inv9" and a["rec_index"] == 0
        assert a["text"] == "Move the cut-off to 14:00" and a["executable"] is True

    def test_no_play_and_no_investigation_means_no_action(self, monkeypatch):
        monkeypatch.setattr("aughor.playbook.retriever.retrieve_for_metric_and_phases", lambda *a, **k: [])
        assert best_action_for({"angle": "x", "domain": "y"}) is None
        assert best_action_for({}) is None

    def test_a_playbook_that_fails_hides_the_item_not_the_brief(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("store down")
        monkeypatch.setattr("aughor.playbook.retriever.retrieve_for_metric_and_phases", boom)
        assert best_action_for({"angle": "x"}) is None


class TestTheBriefCarriesIt:
    def test_each_citation_carries_its_action(self, monkeypatch):
        from aughor.knowledge import briefing as B
        monkeypatch.setattr("aughor.playbook.retriever.retrieve_for_metric_and_phases", lambda *a, **k: [_play()])

        class _Prov:
            def complete(self, system, user, response_model, **kw):
                return SimpleNamespace(narrative="Returns rose [1].", headline_theme="Returns",
                                       citations=[SimpleNamespace(ref="1", insight_id="i1", domain="ops", angle="returns", finding="")])
        monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role: _Prov())
        monkeypatch.setattr(B, "update_dossier", lambda *a, **k: None, raising=False)
        out = B.generate_narrative({"ops": [{"id": "i1", "finding": "Return rate rose from 6.1% to 9.4%", "novelty": 3,
                                             "confidence": 0.8, "angle": "returns", "sql": "SELECT 1"}]}, [], "c1")
        assert out["citations"][0]["action"]["kind"] == "play"
        assert out["citations"][0]["action"]["text"] == "Pause the two lowest-margin carriers"
