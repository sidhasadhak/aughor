"""B2 — walking a design without running it.

A design could be inspected AFTER it ran and never tried BEFORE it was armed, so the only
way to learn what an automation would do was to let it do it, to real people.

The plan said the harness already existed — `evals/equivalence.py` runs automations
`persist=False` with an inert dispatch. Measured first, and it does not: that dispatcher
publishes nothing, so every step after the first came back "upstream data unavailable".
It would have reported a working chain as broken.

What this file locks is everything a preview must NOT do. Each one was found by reading
the engine rather than by guessing, and each is silent when it goes wrong — which is why
they are tested here and not left to a reviewer:

* **No delivery claim.** `claim_delivery` is what stops the next tick re-sending; a
  preview that claimed a period would SILENCE the real run.
* **No baseline commit.** `commit_fired_baselines` runs regardless of `persist`, so a
  preview would consume a source change and the real tick would find nothing new.
* **No span.** VA-4d made the run id the trace id, so a dry run under a span appears in
  `Activity` as a run that happened.
* **No stored run.** Same reason, one layer up.

And the one thing it must do that a real run does not: **let the chain flow**, so a
preview of a sound design reads as sound.
"""
from __future__ import annotations

import pytest

from aughor.automations.engine import dry_sample, run_automation
from aughor.automations.models import Automation, Condition, Effect


def _chain(*effects, **over) -> Automation:
    return Automation(
        conn_id="conn-dry", name="preview", max_retries=0,
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
        effects=list(effects), **over)


def _investigate(alias="numbers") -> Effect:
    return Effect(kind="investigate", alias=alias, config={"question": "how were sales?"})


def _post(**over) -> Effect:
    cfg = {"bot_id": "b1", "channel": "#ops"}
    cfg.update(over.pop("config", {}))
    return Effect(kind="slack_post", config=cfg, **over)


# ── it dispatches nothing ────────────────────────────────────────────────────────

def test_a_real_dispatcher_HANDED_to_a_preview_is_still_not_called():
    """`dry_run` overrides `dispatch` rather than defaulting it. A preview that can be
    handed a real dispatcher is not a preview, and "the caller passed one" is not a
    reason to send a message to a real channel."""
    dispatched: list[str] = []

    def _real(effect, automation):
        dispatched.append(effect.kind)
        raise AssertionError("a preview dispatched an effect")

    run = run_automation(_chain(_investigate(), _post()), dry_run=True, dispatch=_real)
    assert dispatched == [], "the passed dispatcher must never be reached"
    assert [o.status for o in run.effects] == ["executed", "executed"]


def test_the_outward_kinds_are_reported_not_sent():
    """`slack_post` is the one that reaches a real channel. It must read as intent."""
    run = run_automation(_chain(_post()), dry_run=True)
    assert run.effects[0].status == "executed"
    assert run.effects[0].message.startswith("would run")
    assert "#ops" in run.effects[0].message


# ── it writes nothing ────────────────────────────────────────────────────────────

def test_no_delivery_is_CLAIMED(monkeypatch):
    """The claim is what stops the next tick re-sending. A preview that claimed a period
    would silence the real run — the worst failure available to this feature."""
    from aughor.automations import engine
    claims: list[str] = []
    monkeypatch.setattr(engine, "claim_delivery",
                        lambda aid, started: claims.append(aid) or True)
    run_automation(_chain(_post()), dry_run=True)
    assert claims == []


def test_no_source_BASELINE_is_committed(monkeypatch):
    """`commit_fired_baselines` runs regardless of `persist`: a preview would consume the
    change, and the real tick at 09:00 would then not fire."""
    from aughor.automations import probes
    committed: list[str] = []
    monkeypatch.setattr(probes, "commit_fired_baselines",
                        lambda a: committed.append(a.id))

    source = Automation(conn_id="conn-dry", name="preview", max_retries=0,
                        conditions=[Condition(kind="source_change",
                                              config={"table": "public.orders"})],
                        effects=[_post()])
    run_automation(source, dry_run=True)
    assert committed == [], "a preview consumed a source change"


def test_no_SPAN_is_emitted(monkeypatch):
    """VA-4d made the run id the trace id. A dry run under a span appears in `Activity`
    as a run that happened.

    The REAL run is exercised first, and asserted to span — without that control this
    test passes just as well when telemetry is off, on a typo in the patched name, or on
    an import path that moved: a spy that can never fire proves nothing.
    """
    import aughor.telemetry as telemetry
    from aughor.automations.models import EffectOutcome
    spans: list[str] = []
    original = telemetry.mlflow_tool_span
    monkeypatch.setattr(
        telemetry, "mlflow_tool_span",
        lambda name, attrs=None, **kw: (spans.append(name), original(name, attrs, **kw))[1],
        raising=False)

    run_automation(_chain(_investigate(), _post()), persist=False,
                   probe=lambda *a, **k: True, sleeper=lambda _s: None,
                   dispatch=lambda e, a: EffectOutcome(kind=e.kind, target="t",
                                                       status="executed"))
    assert spans == ["automation.investigate", "automation.slack_post"], "control failed"

    spans.clear()
    run_automation(_chain(_investigate(), _post()), dry_run=True)
    assert spans == []


def test_persist_cannot_be_forced_back_on():
    """`dry_run=True` overrides it rather than trusting every caller to pass both. One
    call site forgetting `persist=False` would write a preview into run history."""
    from aughor.automations import engine
    stored: list[str] = []
    original = engine.append_run
    try:
        engine.append_run = lambda run: stored.append(run.id) or run
        run_automation(_chain(_post()), dry_run=True, persist=True)
    finally:
        engine.append_run = original
    assert stored == []


# ── it answers the questions a preview is for ────────────────────────────────────

def test_a_DISABLED_and_not_due_automation_still_previews():
    """The two states a design spends all of its life in before it goes live. Gating on
    either answers nothing; measured live while W1 was proved — three consecutive
    run-nows returned `not_fired` on a daily cron."""
    run = run_automation(_chain(_post(), enabled=False), dry_run=True)
    assert run.outcome == "fired"
    assert "nothing was sent" in run.reason and "disabled" in run.reason


def test_the_reason_still_names_what_would_gate_it():
    """Bypassing the gate is not the same as hiding it. A preview of a paused automation
    that did not say "paused" would be its own lie."""
    run = run_automation(_chain(_post(), paused_until="2099-01-01T00:00:00Z"), dry_run=True)
    # The engine's own word for `paused_until` is "muted" (`_gated`) — asserted as the
    # engine spells it, because a preview quoting a gate in different words is a second
    # vocabulary for one state.
    assert "muted" in run.reason


def test_the_conditions_are_DESCRIBED_using_the_canvas_wording():
    """The trigger node and the preview must not word one condition differently."""
    run = run_automation(_chain(_post()), dry_run=True)
    assert run.conditions_fired == ["schedule · 0 9 * * *"]


def test_the_chain_FLOWS_so_a_sound_design_reads_as_sound():
    """The measured reason the existing inert dispatcher could not be reused."""
    run = run_automation(
        _chain(_investigate(), _post(config={"message": {"$from": "numbers.answer"}})),
        dry_run=True)
    assert [o.status for o in run.effects] == ["executed", "executed"]
    assert "upstream data unavailable" not in run.effects[1].message


def test_a_guard_is_reported_and_the_step_still_runs():
    """A sample cannot answer "will tomorrow's number clear this threshold"."""
    run = run_automation(
        _chain(_investigate(),
               _post(when=[{"left": {"$from": "numbers.answer"}, "op": "truthy"}])),
        dry_run=True)
    assert run.effects[1].status == "executed"
    assert "only if numbers.answer is set — checked when it runs" in run.effects[1].message


def test_a_real_run_is_untouched_by_any_of_this():
    """Every existing caller is byte-identical: `dry_run` defaults off, and with it off
    nothing above is reachable."""
    seen: list[str] = []

    def _dispatch(effect, automation):
        from aughor.automations.models import EffectOutcome
        seen.append(effect.kind)
        return EffectOutcome(kind=effect.kind, target="t", status="executed")

    run = run_automation(_chain(_post()), persist=False, dispatch=_dispatch,
                         probe=lambda *a, **k: True, sleeper=lambda _s: None)
    assert seen == ["slack_post"], "a real run must still dispatch"
    assert "dry run" not in run.reason


# ── the sample ───────────────────────────────────────────────────────────────────

def test_a_step_samples_the_keys_it_DECLARES():
    assert dry_sample("numbers", _investigate(), []) == {
        "answer": "«numbers.answer»", "investigation_id": "«numbers.investigation_id»"}


def test_a_step_also_samples_whatever_a_LATER_step_asks_of_it():
    """The open set, handled without guessing. A declared-action step's outcome shape is
    unknowable — `validate_chain` accepts bindings onto it unchecked for that reason — so
    the sample reads the question from the steps that ask it, through the same
    `effect_refs` the rest of this seam derives from."""
    act = Effect(kind="kinetic_action", alias="act", config={"action_id": "a1"})
    later = [_post(config={"message": {"$from": "act.receipt_url"}})]
    assert dry_sample("act", act, later) == {"receipt_url": "«act.receipt_url»"}


def test_a_key_asked_for_by_a_GUARD_is_sampled_too():
    """W1's guards read the chain exactly as params do, so a preview must feed them."""
    act = Effect(kind="kinetic_action", alias="act", config={"action_id": "a1"})
    later = [_post(when=[{"left": {"$from": "act.status"}, "op": "eq", "right": "ok"}])]
    assert "status" in dry_sample("act", act, later)


@pytest.mark.parametrize("value", ["«numbers.answer»"])
def test_a_sample_is_visibly_a_sample(value):
    """It reaches a screen. A plausible-looking value in a preview is how someone comes
    to believe a number they were never shown."""
    run = run_automation(_chain(_investigate(), _post()), dry_run=True)
    assert run.effects[0].data["answer"] == value
