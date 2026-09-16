"""SP-M — draft the thirty authoring asks ONCE, and record what was staged.

THE ONE SPENDING STEP of the measurement, run only on the user's word: each ask goes
through the real converse loop with the real coder model, so ~30 asks cost roughly
30–90 model calls. Everything after this is free — `aughor.agent.authoring_measure`
scores the recordings in CI with no model, forever.

Isolation: every store is redirected to a scratch directory (the same
`_isolate_stores` the OpenAPI dump uses, since 2026-09-15 covering ALL stores), so
nothing here stages onto the live inbox or touches `data/`. Only the MODEL is live.

Usage:
    .venv/bin/python scripts/record_authoring_drafts.py --yes-spend [--connection ID]

Writes ``evals/authoring/recorded.jsonl`` — one line per ask: the ask, the tool calls
the model chose, every staged proposal row (params + detail, verbatim), and the final
answer. Re-running OVERWRITES: the corpus is drafted once per deliberate run, not
accreted.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dump_openapi import _isolate_stores  # noqa: E402


def _seed(connection_id: str) -> None:
    """The records the corpus's edit/state/brief asks refer to — a scratch deployment
    with nothing on it would turn every one of them into a not-found refusal, which
    measures the fixture, not the drafting."""
    from aughor.automations.models import Automation, Condition, Effect
    from aughor.automations.store import upsert_automation
    from aughor.custom_agents.store import create_agent
    from aughor.notifications.models import ActionTrigger
    from aughor.notifications.store import save_trigger
    from aughor.semantic.metrics import MetricDefinition, save_metric

    save_trigger(ActionTrigger(id="trig-slack", name="Ops Slack", type="slack",
                               url="https://hooks.example/ops", channel="#ops"))
    for name, sql in (("refund_rate", "SUM(refunded)/COUNT(*)"),
                      ("aov", "AVG(order_total)"),
                      ("gross_margin", "SUM(margin)/SUM(revenue)"),
                      ("signup_conversion", "SUM(signed_up)/COUNT(*)"),
                      ("daily_orders", "COUNT(*)")):
        save_metric(MetricDefinition(name=name, label=name.replace("_", " "),
                                     sql=sql, connection=connection_id))
    for name, cron, effect in (
            ("The Monday brief", "0 9 * * 1",
             Effect(kind="notify", config={"trigger_id": "trig-slack"})),
            ("morning anomalies", "0 9 * * *",
             Effect(kind="notify", config={"trigger_id": "trig-slack"})),
            ("daily sales", "0 7 * * *",
             Effect(kind="notify", config={"trigger_id": "trig-slack"})),
            ("old test automation", "0 3 * * *",
             Effect(kind="notify", config={"trigger_id": "trig-slack"}))):
        upsert_automation(Automation(
            conn_id=connection_id, name=name,
            conditions=[Condition(kind="schedule", config={"cron": cron})],
            effects=[effect]))
    create_agent("The Look Analyst", instructions="Analyse theLook with judgment.",
                 connection_id=connection_id)
    # The first recording's two measured fixture gaps (2026-09-16): with no Slack bot,
    # `slack_post` is UNAVAILABLE and every delivery ask dies on an honest refusal of
    # the fixture, not of the drafting; with no subscription, the `brief` effect has
    # nothing to deliver. TWO bots on purpose: SP-7's sender rule then keeps the bot an
    # OPEN choice unless the ask names one — the open-choice path stays measurable.
    from aughor.slackbots.models import SlackBot
    from aughor.slackbots.store import save_bot
    save_bot(SlackBot(id="sb_fixture_a", name="Aughor", bot_token="xoxb-fixture-a",
                      connection_id=connection_id))
    save_bot(SlackBot(id="sb_fixture_b", name="TheLook Analyst",
                      bot_token="xoxb-fixture-b", connection_id=connection_id))
    from aughor.briefing.models import BriefSubscription
    from aughor.briefing.store import save_subscription
    save_subscription(BriefSubscription(conn_id=connection_id, name="Weekly briefing",
                                        period="week", trigger_id="trig-slack"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes-spend", action="store_true",
                    help="acknowledge that this run spends real model calls")
    ap.add_argument("--connection", default="fixture",
                    help="connection id to draft against (default: the builtin fixture)")
    args = ap.parse_args()
    if not args.yes_spend:
        print("This drafts 30 asks through the live coder model (~30-90 calls). "
              "Re-run with --yes-spend to proceed.")
        return 2

    _isolate_stores()
    # The live model's credentials ride the project .env (the API loads it the same
    # way at import). Loaded AFTER isolation: load_dotenv never overrides an existing
    # variable, so every scratch store path set above stays scratch.
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass
    _seed(args.connection)
    from aughor.actions.inbox import list_proposals
    from aughor.agent.converse_tools import converse

    corpus = [json.loads(l) for l in
              (Path(__file__).parent.parent / "evals" / "authoring_asks.jsonl")
              .read_text().splitlines() if l.strip()]
    out_path = Path(__file__).parent.parent / "evals" / "authoring" / "recorded.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    records = []
    for row in corpus:
        seen = {p.id for p in list_proposals(args.connection)}
        result = converse(args.connection, row["ask"])
        staged = [p.model_dump() for p in list_proposals(args.connection)
                  if p.id not in seen]
        records.append({
            "id": row["id"], "family": row["family"], "ask": row["ask"],
            "steps": [{"tool": s.tool, "ok": s.ok} for s in result.steps],
            "staged": staged,
            "answer": result.answer or "",
        })
        print(f"{row['id']}: {len(result.steps)} step(s), {len(staged)} staged")

    out_path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    print(f"recorded {len(records)} asks → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
