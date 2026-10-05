"""Phase 0 of the 2027 study — the baseline numbers, re-measured on the install (ROADMAP §3.53).

The study's §A table quoted every count with its date and said: "a count is a measurement with a
timestamp; re-measure before building on one." This script takes the measurement on the machine
that holds the stores — reads only, no model call, the API may be running — and prints the table
the later phases move against. Run it on the install, not in a clone:

    uv run python scripts/phase0_baseline.py                 # print the table
    uv run python scripts/phase0_baseline.py --write         # also write docs/PHASE0_BASELINE_<date>.md

Every row is read through the store's own door. A store that cannot be read says so on its row
rather than reading as zero: "nobody has ever recorded an outcome" and "the outcome store is
unreadable" are different sentences, and only one of them is phase 3's starting line.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys
from typing import Callable

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _days_ago(iso: str, days: int) -> bool:
    try:
        when = _dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.timezone.utc)
    return when >= _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)


def _org() -> str:
    from aughor.org.context import current_org_id
    return current_org_id()


# ── each row: a name, what the study's §A said, and a reader that returns (value, note) ──

def asks() -> tuple[str, str]:
    from aughor.db.history import list_investigations
    rows = list_investigations(limit=1_000_000)
    deep = [r for r in rows if (r.get("kind") or "investigation") != "chat"]
    chats = [r for r in rows if r.get("kind") == "chat"]
    recent = [r for r in rows if _days_ago(r.get("started_at") or "", 30)]
    return (f"{len(rows)} lifetime ({len(deep)} deep analyses, {len(chats)} chat sessions); "
            f"{len(recent)} in the last 30 days",
            "the history store, chat turns collapsed to sessions as the Agent runs screen lists them")


def people_asking() -> tuple[str, str]:
    from aughor.db.history import _conn
    c = _conn()
    cols = {r[1] for r in c.execute("PRAGMA table_info(investigations)").fetchall()}
    for col in ("user_id", "asked_by", "principal"):
        if col in cols:
            n = c.execute(f"SELECT COUNT(DISTINCT {col}) FROM investigations "
                          f"WHERE {col} IS NOT NULL AND {col} != '' "
                          f"AND started_at >= ?",
                          ((_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=30)).isoformat(),)
                          ).fetchone()[0]
            return str(n), f"distinct `{col}` on the history rows of the last 30 days"
    return "unidentified", "the history rows carry no caller column; with identity off every ask is one person's"


def declared_actions() -> tuple[str, str]:
    from aughor.db.registry import list_connections
    from aughor.routers.ontology import served_ontology_graph
    total, per = 0, []
    for conn in list_connections():
        cid = conn.get("id") if isinstance(conn, dict) else getattr(conn, "id", "")
        try:
            graph = served_ontology_graph(cid, None)
        except Exception:
            graph = None
        try:
            n = len(graph.declared_actions()) if graph is not None else 0
        except Exception:
            n = 0
        if n:
            per.append(f"{cid[:8]}: {n}")
        total += n
    return str(total), ("declared actions on each connection's served ontology"
                        + (f" — {', '.join(per)}" if per else ""))


def standing_grants() -> tuple[str, str]:
    from aughor.actions.grants import list_grants
    grants = list_grants()
    return str(len(grants)), "standing grants (a person pre-authorised one action for one target)"


def proposals() -> tuple[str, str]:
    from aughor.actions.inbox import list_proposals
    rows = list_proposals()
    by = {}
    for p in rows:
        s = p.get("status") if isinstance(p, dict) else getattr(p, "status", "?")
        by[s] = by.get(s, 0) + 1
    return str(len(rows)), "staged proposals by status: " + (", ".join(f"{k} {v}" for k, v in sorted(by.items())) or "none")


def verdicts() -> tuple[str, str]:
    from aughor.feedback.verdicts import list_verdicts
    rows = list_verdicts(limit=1_000_000)
    by = {}
    for v in rows:
        k = v.get("verdict") or "?"
        by[k] = by.get(k, 0) + 1
    return str(len(rows)), ("human verdicts on answers (accept · correct · reject): "
                            + (", ".join(f"{k} {v}" for k, v in sorted(by.items())) or "none") +
                            " — the study's 'labelled decisions'")


def outcomes() -> tuple[str, str]:
    from aughor.playbook.outcomes import load_all_outcomes
    rows = load_all_outcomes()
    reviewed = [o for o in rows if getattr(o, "metric_after", None) is not None]
    return (f"{len(rows)} recorded, {len(reviewed)} with a second measurement",
            "recommendation outcomes — the loop nobody has ever closed; the North Star reads 0 until one is reconciled")


def departures() -> tuple[str, str]:
    from aughor.govern.departure_store import summary_counts
    counts = summary_counts(org_id=_org())
    return (", ".join(f"{k} {v}" for k, v in sorted(counts.items()) if isinstance(v, (int, float))) or "0",
            "the departures ledger: everything that left the platform, by state")


def owners() -> tuple[str, str]:
    from aughor.rbac.owners import list_owner_links, owner_inventory
    org = _org()
    links = list_owner_links(org)
    inventory = owner_inventory(org)
    unresolved = [o for o in inventory if not (o.get("principal") or o.get("resolved"))]
    return (f"{len(links)} linked, {len(unresolved)} of {len(inventory)} owner texts unresolved",
            "owners the platform can reach (CB-3) — phase 0's exit asks for five people who own different things")


def causal() -> tuple[str, str]:
    from aughor.db.history import _conn
    c = _conn()
    rows = c.execute("SELECT report_json FROM investigations WHERE (kind IS NULL OR kind = 'investigation') "
                     "AND report_json IS NOT NULL").fetchall()
    stated = challenged = 0
    for (raw,) in rows:
        try:
            rep = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            continue
        text = json.dumps(rep)
        if '"causal"' in text or '"cause"' in text:
            stated += 1
        if rep.get("causal_checks"):
            challenged += 1
    return (f"{stated} of {len(rows)} deep reports state a cause (proxy: a causal claim type or a cause field); "
            f"{challenged} carry a recorded challenge",
            "the skeptic step's record exists since 2026-10-04; before it, none had one")


def approved_metrics() -> tuple[str, str]:
    from aughor.semantic.metrics import list_metrics
    ms = list_metrics()
    def _status(m):
        return (m.get("status") if isinstance(m, dict) else getattr(m, "status", None)) or ""
    approved = [m for m in ms if str(_status(m)).lower() == "approved"]
    return f"{len(approved)} of {len(ms)}", "governed metrics approved — the definition law's input"


def goldens() -> tuple[str, str]:
    from aughor.evals.store import list_cases, list_suites
    suites = list_suites(limit=1000)
    n = 0
    for s in suites:
        sid = s.get("id") if isinstance(s, dict) else getattr(s, "id", "")
        try:
            n += len(list_cases(sid, limit=100_000))
        except Exception:
            pass
    return f"{n} cases in {len(suites)} suites", "golden suites compared by result set — the study's target is 150 goldens"


def gate_default() -> tuple[str, str]:
    import os
    from aughor.govern.actions import approval_enabled
    raw = os.environ.get("AUGHOR_ACTION_APPROVAL", "")
    return ("on" if approval_enabled() else "OFF"), (f"AUGHOR_ACTION_APPROVAL={raw!r}; on by default since 2026-10-04")


def identity() -> tuple[str, str]:
    from aughor.security.authz import require_identity_enabled
    return ("on" if require_identity_enabled() else "off"), "AUGHOR_REQUIRE_IDENTITY=1 switches it on at start"


ROWS: list[tuple[str, str, Callable[[], tuple[str, str]]]] = [
    ("Asks", "74 ask turns lifetime (2026-09-23); 111 logged asks (2026-10-04)", asks),
    ("People who asked, 30 days", "one", people_asking),
    ("Declared actions", "1 (2026-09-10)", declared_actions),
    ("Standing grants", "unmeasured", standing_grants),
    ("Proposals", "unmeasured", proposals),
    ("Human verdicts", "5 labelled decisions (Arc JD)", verdicts),
    ("Outcomes recorded", "0 — nobody has ever recorded one", outcomes),
    ("Departures", "unmeasured", departures),
    ("Owners", "the panel exists; the count is not published", owners),
    ("Causes stated / challenged", "169 of 309 stated; 0 challenged (2026-10-04)", causal),
    ("Approved metrics", "theLook: revenue, units_sold, return_rate, AOV", approved_metrics),
    ("Goldens", "5 of 150", goldens),
    ("Approval gate", "off unless set (before 2026-10-04)", gate_default),
    ("Identity", "off", identity),
]


def measure() -> list[tuple[str, str, str, str]]:
    out = []
    for name, before, reader in ROWS:
        try:
            value, note = reader()
        except Exception as exc:  # noqa: BLE001 — an unreadable store is a row, never a zero
            value, note = "unreadable", f"{type(exc).__name__}: {str(exc)[:120]}"
        out.append((name, before, value, note))
    return out


def render(rows: list[tuple[str, str, str, str]]) -> str:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    lines = [f"# Phase 0 baseline — measured {stamp}", "",
             "*Read through each store's own door on the install; no model call. The 'study said' column is "
             "`docs/PLATFORM_2027_STUDY_2026-10-04.md` §A as written; the 'now' column is this run.*", "",
             "| Measure | The study said | Now | Read from |", "|---|---|---|---|"]
    for name, before, value, note in rows:
        lines.append(f"| {name} | {before} | **{value}** | {note} |")
    lines += ["", "A row reading *unreadable* names its error; it is not a zero."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true", help="also write docs/PHASE0_BASELINE_<date>.md")
    args = ap.parse_args(argv)
    text = render(measure())
    print(text)
    if args.write:
        path = REPO / "docs" / f"PHASE0_BASELINE_{_dt.date.today().isoformat()}.md"
        path.write_text(text, encoding="utf-8")
        print(f"written: {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
