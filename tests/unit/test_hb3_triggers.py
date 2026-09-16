"""HB-3 — the hub's two trigger kinds and the payload they hand the chain.

`promise_breached` and `finding_created` are READS of what the platform already
measured or stored (a probe never builds); their payload seeds the reserved `trigger`
alias so a step binds `{"$from": "trigger.breach_rate"}` like any prior step's key —
and a typo on that key is a save-time sentence, not a skipped step at 09:00.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aughor.automations import probes as P
from aughor.automations.engine import evaluate_conditions, run_automation
from aughor.automations.models import Automation, Condition, Effect

_NOW = datetime(2026, 9, 16, 9, 0, tzinfo=timezone.utc)


def _auto(cond: dict, effects=None, **kw) -> Automation:
    return Automation(id=kw.pop("id", "hb3auto"), conn_id=kw.pop("conn_id", "c1"),
                      name="hb3", conditions=[cond],
                      effects=effects or [Effect(kind="notify",
                                                 config={"trigger_id": "t1"})], **kw)


def _promise_row(**over):
    row = {"name": "dispatch", "process": "order_to_delivery", "stage": "shipped",
           "process_owner": "group:supply-chain", "breached": 120, "reached": 1283,
           "breach_rate": 0.0935, "as_of": "2018-08-29", "segment": "late_orders"}
    row.update(over)
    return row


# ── promise_breached ──────────────────────────────────────────────────────────────

def test_first_sight_of_a_broken_promise_fires_with_the_payload(monkeypatch):
    monkeypatch.setattr(P, "_promise_rows", lambda a, c: ([_promise_row()], ""))
    cond = Condition(kind="promise_breached", config={"process": "order_to_delivery"})
    fired, detail, payload = P.evaluate_promise_condition(cond, _auto(cond.model_dump()))
    assert fired and "first observation" in detail
    assert payload["about"] == "promise:order_to_delivery.dispatch"
    assert payload["process_securable"] == "process:order_to_delivery"
    assert payload["breach_rate"] == 0.0935 and payload["owner"] == "group:supply-chain"


def test_a_kept_promise_stays_quiet(monkeypatch):
    monkeypatch.setattr(P, "_promise_rows",
                        lambda a, c: ([_promise_row(breached=0)], ""))
    cond = Condition(kind="promise_breached", config={"process": "order_to_delivery"})
    fired, detail, payload = P.evaluate_promise_condition(cond, _auto(cond.model_dump()))
    assert not fired and "kept" in detail and payload == {}


def test_unchanged_since_last_fired_stays_quiet_and_worsening_fires(monkeypatch):
    monkeypatch.setattr(P, "_promise_rows", lambda a, c: ([_promise_row()], ""))
    auto = _auto({"kind": "promise_breached", "config": {"process": "order_to_delivery"}})
    cond = auto.conditions[0]
    from aughor.automations.store import set_probe_baseline
    set_probe_baseline(auto.id, "promise:order_to_delivery.dispatch",
                       "breached=120|rate=0.0935")
    fired, detail, _ = P.evaluate_promise_condition(cond, auto)
    assert not fired and "unchanged" in detail
    monkeypatch.setattr(P, "_promise_rows",
                        lambda a, c: ([_promise_row(breached=131, breach_rate=0.102)], ""))
    fired, detail, payload = P.evaluate_promise_condition(cond, auto)
    assert fired and payload["breached"] == 131


def test_an_undeclared_process_is_a_loud_probe_failure(monkeypatch):
    from aughor.automations.engine import ProbeUnavailable
    monkeypatch.setattr(P, "_promise_rows", lambda a, c: ([], "promise_breached(x): process not declared"))
    cond = Condition(kind="promise_breached", config={"process": "x"})
    with pytest.raises(ProbeUnavailable):
        P.evaluate_promise_condition(cond, _auto(cond.model_dump()))


def test_commit_advances_the_promise_fingerprint(monkeypatch):
    monkeypatch.setattr(P, "_promise_rows", lambda a, c: ([_promise_row()], ""))
    auto = _auto({"kind": "promise_breached", "config": {"process": "order_to_delivery"}},
                 id="hb3commit")
    P.commit_hub_baselines(auto)
    from aughor.automations.store import get_probe_baseline
    assert get_probe_baseline("hb3commit",
                              "promise:order_to_delivery.dispatch") == "breached=120|rate=0.0935"


# ── finding_created ───────────────────────────────────────────────────────────────

def _findings():
    return [
        {"id": "f1", "finding": "AOV fell.", "domain": "revenue", "confidence": 0.6,
         "generated_at": "2026-09-15T08:00:00Z"},
        {"id": "f2", "finding": "Carrier X is late in the south.", "domain": "logistics",
         "confidence": 0.9, "generated_at": "2026-09-16T07:00:00Z"},
    ]


def test_first_observation_fires_with_the_newest_finding(monkeypatch):
    monkeypatch.setattr("aughor.explorer.store.get_findings", lambda cid: _findings())
    cond = Condition(kind="finding_created", config={})
    fired, detail, payload = P.evaluate_finding_condition(cond, _auto(cond.model_dump(), id="hb3f1"))
    assert fired and payload["finding_id"] == "f2" and payload["count_new"] == 2
    assert payload["about"] == "finding:f2"


def test_cursor_quiets_old_findings_and_filters_narrow(monkeypatch):
    monkeypatch.setattr("aughor.explorer.store.get_findings", lambda cid: _findings())
    auto = _auto({"kind": "finding_created", "config": {}}, id="hb3f2")
    P.commit_hub_baselines(auto)          # cursor = newest generated_at
    fired, detail, _ = P.evaluate_finding_condition(auto.conditions[0], auto)
    assert not fired and "nothing newer" in detail
    dom = Condition(kind="finding_created", config={"domain": "logistics",
                                                    "min_confidence": 0.8})
    fired, _, payload = P.evaluate_finding_condition(dom, _auto(dom.model_dump(), id="hb3f3"))
    assert fired and payload["finding_id"] == "f2" and payload["count_new"] == 1


# ── the payload reaches the chain, end to end ─────────────────────────────────────

def test_trigger_payload_binds_into_a_step(monkeypatch):
    seen = {}

    def probe(cond, automation):
        return True, "promise_breached: fired", {"about": "promise:p.d",
                                                 "breach_rate": 0.0935}

    def dispatch(effect, automation):
        from aughor.automations.models import EffectOutcome
        seen["config"] = dict(effect.config)
        return EffectOutcome(kind=effect.kind, target="t1", status="executed")

    auto = _auto({"kind": "promise_breached", "config": {"process": "p"}},
                 effects=[Effect(kind="notify", config={
                     "trigger_id": "t1",
                     "message": {"$from": "trigger.breach_rate", "$as": "text"},
                     "about": {"$from": "trigger.about"}})],
                 id="hb3bind")
    run = run_automation(auto, now=_NOW, probe=probe, dispatch=dispatch,
                         persist=False, via="schedule")
    assert run.outcome == "fired", run.reason
    assert seen["config"]["message"] == "0.0935"
    assert seen["config"]["about"] == "promise:p.d"


def test_evaluate_conditions_collects_payloads_without_changing_its_shape():
    out: dict = {}
    auto = _auto({"kind": "promise_breached", "config": {"process": "p"}})
    fired, details, reason = evaluate_conditions(
        auto, now=_NOW, trigger_data=out,
        probe=lambda c, a: (True, "ok", {"breach_rate": 0.1}))
    assert fired and out == {"breach_rate": 0.1}


# ── save-time law for trigger refs ────────────────────────────────────────────────

def test_a_trigger_ref_is_validated_at_save():
    good = _auto({"kind": "promise_breached", "config": {"process": "p"}},
                 effects=[Effect(kind="notify", config={
                     "trigger_id": "t1", "message": {"$from": "trigger.breach_rate"}})])
    assert good.effects[0].config["message"] == {"$from": "trigger.breach_rate"}

    with pytest.raises(Exception, match="trigger publishes"):
        _auto({"kind": "promise_breached", "config": {"process": "p"}},
              effects=[Effect(kind="notify", config={
                  "trigger_id": "t1", "message": {"$from": "trigger.no_such_key"}})])

    with pytest.raises(Exception, match="publishes a payload"):
        _auto({"kind": "schedule", "config": {"cron": "0 9 * * *"}},
              effects=[Effect(kind="notify", config={
                  "trigger_id": "t1", "message": {"$from": "trigger.breach_rate"}})])


def test_the_trigger_alias_is_reserved():
    with pytest.raises(Exception, match="reserved"):
        _auto({"kind": "schedule", "config": {"cron": "0 9 * * *"}},
              effects=[Effect(kind="notify", alias="trigger",
                              config={"trigger_id": "t1"})])
