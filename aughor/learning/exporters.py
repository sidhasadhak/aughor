"""Turning graded rows into corpora — SFT, DPO and the held-out golden set.

Three properties this file exists to guarantee, each of which has a test:

* **Deterministic.** The same graded rows export to the same content hash, every time.
  Without that an adapter's provenance cites a moving target.
* **Disjoint.** A golden example is never also a training example. A corpus that trains on
  its own benchmark cannot be measured by it, and the split is by a STABLE hash of the
  QUESTION, not by shuffling — a random split would move every re-export. It was keyed on
  the answer's id until PENDING item 23, so the same question asked twice could land on
  both sides; now a question is held out or not wherever it appears, and no trainable
  corpus carries a golden row's question or its SQL.
* **Scrubbed.** Text goes through the existing `security/pii` seam on the way out, per
  §6.7's annex. Reusing that seam rather than writing a second scrubber is deliberate: two
  redaction implementations means two definitions of what counts as PII.

**Measured before writing (2026-09-03).** The live store holds 5 verdicts: 2 accept, 1
correct, 2 reject, and **none carries `sql_source` or `corrected_sql`** — so these
exporters produce ~0 examples on this deployment today. That is the honest state, and it
is the arc's own prediction (§3.9: *capture is already rich; grading is the gap*), not a
defect here. MI-4's gates — 1,000 SFT / 150 DPO / 150 golden — are measured against these
outputs precisely so the distillation premise stays falsifiable.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import NamedTuple, Optional

from aughor.learning import store

#: Share of accepted findings held out as golden. A tenth is enough to measure and cheap
#: to give up; the split is by stable hash so it does not drift between exports.
_GOLDEN_SHARE = 10


def _scrub(text: str) -> str:
    """One text field through the platform's PII seam.

    The seam is tabular (it was built for query results), so a field is presented as a
    one-cell row. Worth the small awkwardness: a second scrubber would be a second
    definition of PII, and the two would drift."""
    if not text:
        return text
    try:
        from aughor.security.pii import PiiScanner
        res = PiiScanner.scan_and_redact(["text"], [[text]])
        return res.rows[0][0] if res.rows and res.rows[0] else text
    except Exception:
        from aughor.kernel.errors import tolerate
        tolerate(Exception("pii scrub failed"),
                 "an export that cannot be scrubbed must not ship unscrubbed",
                 counter="learning.scrub")
        return ""      # fail CLOSED: drop the text rather than export it unredacted


def _is_golden(verdict_row: dict) -> bool:
    """Stable, content-derived hold-out. Deliberately NOT random: a shuffled split would
    move examples between corpora on every export and break both determinism and the
    promise that a golden example was never trained on. Decision records split by their
    record id; question→SQL rows split by their question (`_held_out`)."""
    key = str(verdict_row.get("investigation_id") or verdict_row.get("id") or "")
    fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(fingerprint[:8], 16) % _GOLDEN_SHARE == 0


def _question_key(question: str) -> str:
    """A question as the split sees it: case, punctuation and spacing are not a different question."""
    return " ".join(re.sub(r"[^\w\s]", " ", str(question or "").lower()).split())


def _sql_key(sql: str) -> str:
    from aughor.feedback.verdicts import sql_key
    return sql_key(sql)


def _held_out(question: str) -> bool:
    """The stable tenth, decided by the QUESTION (PENDING item 23). Keyed on the answer's id, the same question asked
    twice — the commonest shape of a real corpus — landed on both sides of the split, so a model could train on the
    very question it was then measured by. Decided before any data is seen, so a question that joins the golden set
    later was never trained on either."""
    return _is_golden({"id": _question_key(question)})


class _Held(NamedTuple):
    """The golden set's rows, and what no trainable corpus may carry: their questions and their SQL. The SQL mark
    catches the paraphrase the question hash cannot ("revenue last month" held out, "last month's revenue" trained
    on, one query)."""
    verdicts: list
    trusted: list
    agent: list
    questions: frozenset
    sqls: frozenset

    def admits(self, question: str, sql: str) -> bool:
        return (not _held_out(question) and _question_key(question) not in self.questions
                and _sql_key(sql) not in self.sqls)


def _sources(limit: int) -> tuple[list[dict], list, _Held]:
    """Every graded source, reconciled and scoped, with the golden set taken out first — so the trainable exporters
    and the golden one read the same split and cannot drift apart."""
    verdicts = _reconciled_verdicts()[:limit]
    trusted = [t for t in _trusted_export_rows() if _in_org(t.connection_id)]
    held_verdicts = [r for r in verdicts if r["verdict"] == "accept" and r["sql_ran"]
                     and r["question"] and _held_out(r["question"])]
    held_trusted = [t for t in trusted if _held_out(t.question)]
    agent = _agent_golden_rows()
    pairs = ([(r["question"], r["sql_source"]) for r in held_verdicts] + [(t.question, t.sql) for t in held_trusted]
             + [(g["question"], g["reference_sql"]) for g in agent])
    return verdicts, trusted, _Held(held_verdicts, held_trusted, agent,
                                    frozenset(_question_key(q) for q, _ in pairs),
                                    frozenset(_sql_key(s) for _, s in pairs))


def _dedupe(examples: list[dict]) -> list[dict]:
    """Aggressive dedupe, first occurrence wins. Duplicated examples do not add signal;
    they add WEIGHT, quietly training the model harder on whatever happens to repeat."""
    seen: set[str] = set()
    out: list[dict] = []
    for ex in examples:
        key = hashlib.sha256(
            (str(ex.get("prompt", "")) + "\x00" + str(ex.get("completion", ""))
             + "\x00" + str(ex.get("rejected", ""))).encode("utf-8")).hexdigest()
        if key not in seen:
            seen.add(key)
            out.append(ex)
    return out


def _trusted_export_rows() -> list:
    """Approved trusted queries whose approval was a HUMAN act — KI-4's addition to
    the corpus. A human-approved (question, SQL) pair is the purest SFT example the
    platform produces: the two-act door (§6 item 9b) means someone verified it ran
    clean AND someone chose to trust it. Excluded deliberately: eval-promoted entries
    (their warrant is consistency — "reproduces a prior answer", not "is true" — and
    §3.9's reward-integrity law keeps the corpus human-graded) and grandfathered
    legacy rows with no verifier of record."""
    from aughor.semantic.trusted_queries import list_trusted

    return [t for t in list_trusted()          # approved-only by default (fail closed)
            if (t.verified_by or "").strip()
            and t.source != "eval_promotion"
            and (t.question or "").strip() and (t.sql or "").strip()]


def _agent_golden_rows() -> list[dict]:
    """Per-agent goldens — human-authored (question, reference_sql) regression pairs.

    The third graded source, joined 2026-09-06: five live, verified pairs (The Look
    Analyst's BigQuery goldens among them) sat off-feed while the gate report read
    zero. They are benchmark-natured BY ROLE — these rows ARE each agent's own eval
    suite — so they feed ONLY the golden set, never SFT or DPO: splitting them like
    verdicts would train an adapter on the very cases its agent is measured by, the
    literal form of §3.9's train-on-its-own-benchmark refusal.
    """
    from aughor.custom_agents.store import list_agents, list_goldens

    out: list[dict] = []
    for agent in list_agents():
        if not _in_org(getattr(agent, "connection_id", "") or ""):
            continue                # another organisation's agent (PENDING item 23: export was unscoped)
        for g in list_goldens(agent.id):
            if (g.get("question") or "").strip() and (g.get("reference_sql") or "").strip():
                out.append(g)
    return out


def _reconciled_verdicts() -> list[dict]:
    """Every verdict this organisation recorded, reduced to each answer's LATEST, oldest first, each with the
    ``question`` its answer was asked by ("" when none was).

    PENDING item 23: an accept stayed exportable after a later reject of the same answer, so a corpus could train on
    SQL a person had since called wrong. Reconciled over every verdict — with SQL or without — before any exporter
    filters, so a later verdict that carries no SQL still overrules an earlier one that does."""
    from aughor.feedback.verdicts import list_for_export
    latest: dict[str, dict] = {}
    for r in list_for_export(("accept", "correct", "reject"), require_sql=False):
        latest[str(r.get("investigation_id") or f"verdict:{r['id']}")] = r
    out = []
    for r in sorted(latest.values(), key=lambda r: r["id"]):
        question, ran = _answer_of(r)
        out.append({**r, "question": question,
                    "sql_ran": bool(r.get("sql_source")) and _sql_key(r["sql_source"]) in ran})
    return out


def _answer_of(verdict: dict) -> tuple[str, set[str]]:
    """The question a person asked, for the answer a verdict graded, and the SQL that answer RAN — ("", set()) when
    there is no such answer in this organisation.

    The corpora used the answer's HEADLINE as the prompt (every door sends it), which trains a model to map a
    result's statement to SQL, not a question. A verdict on an explorer finding has no question at all — its
    headline states what the SQL found — so it is left out of a question→SQL corpus rather than dressed up as one.

    The SQL is what makes an accept worth training on, and the verdict's ``sql_source`` is whatever the door POSTED:
    anyone who can grade an answer could otherwise put SQL the answer never ran into the silver tier under a
    person's name. So a verdict's SQL counts only when the answer's own record holds it."""
    inv_id = str(verdict.get("investigation_id") or "")
    if not inv_id:
        return "", set()
    try:
        from aughor.db.history import get_investigation
        from aughor.org.context import current_org_id
        inv = get_investigation(inv_id) or {}
        if (inv.get("org_id") or "default") != (current_org_id() or "default"):
            return "", set()               # history is not org-scoped by id; the corpus is
    except Exception as exc:  # noqa: BLE001 — an unreadable history row is a row without a question
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the verdict's question could not be read; the row is left out", counter="learning.question")
        return "", set()
    from aughor.db.history import sql_ran_by
    return str(inv.get("question") or "").strip(), {_sql_key(sql) for sql in sql_ran_by(inv)}


def _dialects() -> dict[str, str]:
    try:
        from aughor.db.registry import list_connections
        return {c["id"]: str(c.get("db_type") or c.get("type") or "") for c in list_connections()}
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "connection dialects unreadable; rows export without one", counter="learning.dialects")
        return {}


def _context(connection_id: str, sql: str, dialects: dict[str, str]) -> dict:
    """What a row was answered AGAINST: its connection, that connection's dialect, and the tables its SQL reads.
    Without it a corpus teaches question→SQL with the warehouse left out (docs/ENGINE_REVIEW_ANSWERS_2026-09-24.md
    §3) — two connections' "revenue" become one example."""
    tables: list[str] = []
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read=dialects.get(connection_id) or None)
        ctes = {(c.alias_or_name or "").lower() for c in tree.find_all(exp.CTE)}
        tables = sorted({t.sql() for t in tree.find_all(exp.Table) if (t.name or "").lower() not in ctes})
    except Exception as exc:  # noqa: BLE001 — a row whose SQL will not parse keeps its SQL, without tables
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a row's SQL did not parse for its tables", counter="learning.context_tables")
    return {"connection_id": connection_id, "dialect": dialects.get(connection_id, ""), "tables": tables}


def _in_org(connection_id: str) -> bool:
    """A source row belongs to the exporting organisation when its connection does — or to everyone, on a shared
    builtin. Trusted queries and agents carry no org of their own; their connection does (DATA-06)."""
    from aughor.org.context import current_org_id
    try:
        from aughor.db.registry import get_connection_org
        owner = get_connection_org(connection_id)
    except Exception as exc:  # noqa: BLE001 — unknown ownership fails CLOSED for an export
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a row's connection owner was unreadable; it is left out of the export",
                 counter="learning.org_scope")
        return False
    return owner is None or owner == current_org_id()


def _runs(connection_id: str, sql: str, cache: dict) -> str:
    """"" when ``sql`` binds on its connection (a dry run), else why not — a typed correction became the DPO "chosen"
    SQL without ever being run, so a typo trained as the right answer."""
    try:
        if connection_id not in cache:
            from aughor.db.connection import open_connection_for
            cache[connection_id] = open_connection_for(connection_id)
        ok, err = cache[connection_id].dry_run(sql)
        return "" if ok else f"it does not run: {str(err or 'dry run failed')[:160]}"
    except Exception as exc:  # noqa: BLE001 — an unverifiable correction is not exported
        return f"its connection could not run it ({type(exc).__name__})"


def export_sft(name: str = "nl2sql-sft", *, task: str = "nl2sql",
               limit: int = 100000) -> dict:
    """Accepted answers + human-approved trusted queries → question → SQL pairs, the golden
    set's questions and SQL left out (`_sources`)."""
    dialects = _dialects()
    verdicts, trusted_rows, held = _sources(limit)
    kept = [r for r in verdicts if r["verdict"] == "accept" and r["sql_ran"] and r["question"]
            and held.admits(r["question"], r["sql_source"])]
    trusted = [t for t in trusted_rows if held.admits(t.question, t.sql)]
    examples = _dedupe([
        {"prompt": _scrub(r["question"]),
         "completion": _scrub(r.get("sql_source") or ""),
         "context": _context(r.get("connection_id") or "", r.get("sql_source") or "", dialects),
         "tier": "silver", "task": task}
        for r in kept
    ] + [
        {"prompt": _scrub(t.question), "completion": _scrub(t.sql),
         "context": _context(t.connection_id, t.sql, dialects), "tier": "gold", "task": task}
        for t in trusted
    ])
    return store.register(
        name, "sft", examples, task=task,
        lineage=([("finding_verdict", r["id"]) for r in kept]
                 + [("trusted_query", t.id) for t in trusted]))


def export_dpo(name: str = "nl2sql-dpo", *, task: str = "nl2sql",
               limit: int = 100000) -> dict:
    """`correct` verdicts → preference pairs: `sql_source` rejected, `corrected_sql` chosen.

    The platform has been collecting preference data without calling it that — but ONLY
    where a human actually typed a correction. A `correct` verdict with no `corrected_sql`
    is a judgement without a lesson, and including it would fabricate a preference nobody
    expressed."""
    dialects, conns = _dialects(), {}
    verdicts, _, held = _sources(limit)
    rows = [r for r in verdicts
            if r["verdict"] == "correct" and r["sql_ran"]
            and (r.get("corrected_sql") or "").strip() and r["question"]
            and held.admits(r["question"], r["corrected_sql"])]
    rows = [r for r in rows if not _runs(r.get("connection_id") or "", r["corrected_sql"], conns)]
    examples = _dedupe([
        {"prompt": _scrub(r["question"]),
         "completion": _scrub(r.get("corrected_sql") or ""),
         "rejected": _scrub(r.get("sql_source") or ""),
         "context": _context(r.get("connection_id") or "", r.get("corrected_sql") or "", dialects),
         "tier": "silver", "task": task}
        for r in rows
    ])
    return store.register(
        name, "dpo", examples, task=task,
        lineage=[("finding_verdict", r["id"]) for r in rows])


def export_golden(name: str = "nl2sql-golden", *, task: str = "nl2sql",
                  limit: int = 100000) -> dict:
    """The held-out tenth of accepted findings — the ratchet's measuring stick.

    Registered as a dataset like any other so it is versioned and provenanced, but it is
    the one kind MI-4 may never train on. Disjointness from SFT is guaranteed by the same
    predicate that excludes these rows there, so the two cannot drift apart."""
    _, _, split = _sources(limit)
    held, trusted = split.verdicts, split.trusted
    # Agent goldens join WHOLE, not through the tenth-split: every one of them is
    # already a benchmark row (see _agent_golden_rows), so holding out a tenth of a
    # hold-out would just discard nine tenths of the platform's scarcest material.
    agent_goldens = split.agent
    examples = _dedupe([
        {"prompt": _scrub(r["question"]),
         "completion": _scrub(r.get("sql_source") or ""),
         "task": task}
        for r in held
    ] + [
        {"prompt": _scrub(t.question), "completion": _scrub(t.sql), "task": task}
        for t in trusted
    ] + [
        {"prompt": _scrub(g["question"]), "completion": _scrub(g["reference_sql"]),
         "task": task}
        for g in agent_goldens
    ])
    return store.register(
        name, "golden", examples, task=task,
        lineage=([("finding_verdict", r["id"]) for r in held]
                 + [("trusted_query", t.id) for t in trusted]
                 + [("agent_golden", g["id"]) for g in agent_goldens]))


def publish_golden_to_evals(node: dict, *, suite_name: Optional[str] = None) -> Optional[str]:
    """Register a golden dataset as an eval SUITE so the ratchet can actually run it.

    MI-3's receipt is "a golden set shows up in the evals plane", and the word that matters
    is *shows up*: a `golden` row in our own store proves only that we wrote one. The
    evals plane is where promotion gates are enforced, so a held-out set that never lands
    there is a measuring stick nobody measures with — the "tested, not leveraged" shape
    this codebase has paid for four times. Returns the suite id, or None when the set is
    empty (there is nothing to measure, and an empty suite would read as a passing gate).

    The suite name carries the dataset VERSION, so re-publishing a grown golden set makes
    a new suite rather than silently mutating the one a past ratchet result was measured
    against. A baseline whose cases changed underneath it is not a baseline.
    """
    if node.get("kind") != "golden":
        raise ValueError(f"only a golden dataset belongs in the evals plane, got {node.get('kind')!r}")
    rows = store.rows_of(node)
    if not rows:
        return None
    from aughor.evals import store as evals_store

    name = suite_name or f"{node['name']}-v{node['version']}"
    for existing in evals_store.list_suites(limit=500):
        if existing.get("name") == name:
            return existing["id"]          # idempotent: same version, same suite
    suite = evals_store.create_suite(
        name, description=(f"MI-3 golden set — dataset {node['name']} v{node['version']}, "
                           f"{node['row_count']} held-out examples. Never trained on."))
    evals_store.add_cases(suite["id"], [
        {"question": r.get("prompt", ""), "expected": {"sql": r.get("completion", "")},
         "tags": ["golden", "mi-3", node["name"]]}
        for r in rows
    ])
    return suite["id"]


def _answered_turns(limit: int) -> list[dict]:
    """This organisation's completed chat answers that carry a query result, oldest first."""
    from aughor.db.history import recent_chat_answers
    from aughor.org.context import current_org_id
    org = current_org_id()
    return sorted((a for a in recent_chat_answers("0000", limit=limit)
                   if (a.get("org_id") or "default") == org and (a.get("question") or "").strip()),
                  key=lambda a: a.get("completed_at") or "")



#: A receipt whose action replaced the query: its before and after are a wrong-SQL → fixed-SQL pair.
_REWRITE_ACTIONS = frozenset({"rewrote_sql", "repaired_sql"})

#: What a receipt keeps of each side (kernel/registries/execution_hooks.py and the quick path both cut at 2,000).
_RECEIPT_SQL_CAP = 2000


def _guards_clean(report: dict) -> bool:
    from aughor.answer.envelope import guards_clean
    return guards_clean(report.get("envelope"))


def _latest_recheck(report: dict) -> dict:
    checks = [c for c in (report.get("rechecks") or []) if isinstance(c, dict)]
    return checks[-1] if checks else {}


def export_bronze(name: str = "nl2sql-bronze", *, task: str = "nl2sql", limit: int = 20000) -> dict:
    """Question → SQL from answers graded by EXECUTION only — the plentiful tier (PENDING item 23).

    An answer is in when its query ran and returned rows, its guards were clean (no check fired that no rewrite
    cleared, no caveat), no later re-run of its query failed, and no person has rejected or corrected it. That is
    executability, not correctness, which is why it is its own kind (`sft_bronze`), counts toward no MI-4 gate, and
    carries its tier and its latest re-check on every row: ROADMAP §3.9 requires the verifier behind a tier like this
    hand-audited on 50–100 rows before anything trains on it. The one door it was never possible to grade from — the
    chat, where most answers are given — is the one it reads."""
    verdicts, _, held = _sources(100000)
    graded = {str(r.get("investigation_id")): r["verdict"] for r in verdicts}
    # `accepted` means a person accepted THIS query — an accept whose posted SQL the answer never ran is not that
    accepted = {str(r.get("investigation_id")) for r in verdicts if r["verdict"] == "accept" and r["sql_ran"]}
    dialects = _dialects()
    rows = [a for a in _answered_turns(limit)
            if graded.get(a["id"]) not in ("reject", "correct") and a["report"].get("rows")
            and _guards_clean(a["report"])
            and not str(_latest_recheck(a["report"]).get("reason") or "").startswith("re-running its query failed")
            and held.admits(a["question"], a["report"].get("sql") or "")]
    examples = _dedupe([
        {"prompt": _scrub(a["question"]), "completion": _scrub(a["report"]["sql"]),
         "context": _context(a.get("connection_id") or "", a["report"]["sql"], dialects),
         "tier": "bronze", "accepted": a["id"] in accepted,
         "rechecked": str(_latest_recheck(a["report"]).get("status") or ""), "task": task}
        for a in rows
    ])
    return store.register(name, "sft_bronze", examples, task=task,
                          lineage=[("chat_answer", a["id"]) for a in rows])


def export_repair_pairs(name: str = "nl2sql-repairs", *, task: str = "nl2sql", limit: int = 20000) -> dict:
    """Wrong SQL → fixed SQL, from the rewrites the guards already made — free preference pairs (PENDING item 23).

    When a guard rewrote a query (the fan-out de-fan, the lint fix, the preflight repair, the repair after a failed
    run), the answer's envelope kept the SQL before and after; each rewrite was adopted only once it bound, and each
    names the class of mistake it fixed. They were kept as a 120-character prefix in the guard log and nowhere as
    pairs. Their own kind (`dpo_repair`): a guard's rewrite is a known mistake's known fix, not a person's
    preference, so it counts toward no gate. A side the receipt cut at its cap is a truncated query, so that pair is
    left out rather than taught."""
    dialects = _dialects()
    _, _, held = _sources(100000)
    pairs, lineage = [], []
    for a in _answered_turns(limit):
        receipts = (((a["report"].get("envelope") or {}).get("provenance") or {}).get("guard_receipts") or [])
        for r in receipts:
            before, after = str(r.get("before") or "").strip(), str(r.get("after") or "").strip()
            if (r.get("action") in _REWRITE_ACTIONS and before and after and before != after
                    and max(len(str(r.get("before"))), len(str(r.get("after")))) < _RECEIPT_SQL_CAP
                    and held.admits(a["question"], after)):
                pairs.append({"prompt": _scrub(a["question"]), "completion": _scrub(after),
                              "rejected": _scrub(before), "guard": str(r.get("guard") or ""),
                              "context": _context(a.get("connection_id") or "", after, dialects),
                              "tier": "guard_rewrite", "task": task})
                lineage.append(("chat_answer", a["id"]))
    return store.register(name, "dpo_repair", _dedupe(pairs), task=task, lineage=lineage)


def export_all(*, task: str = "nl2sql") -> dict[str, dict]:
    """Run every exporter. Idempotent: an unchanged corpus re-registers no new version.

    Metered under the kernel's EXISTING budget when called from a job — never a parallel
    one. Two caps for one population is a trap this repo has already paid for: a limit
    nothing enforces and a limit enforced twice are both wrong, in opposite directions."""
    return {"sft": export_sft(task=task),
            "dpo": export_dpo(task=task),
            "golden": export_golden(task=task),
            "sft_bronze": export_bronze(task=task),
            "dpo_repair": export_repair_pairs(task=task)}


def export_decisions(site: Optional[str] = None, *, task: str = "decision") -> dict[str, dict]:
    """Decision records → selection corpora: `{context, options, label}` rows per site.

    The same three properties the graded exporters guarantee, kept the same way:
    deterministic (identical records hash to the identical snapshot), disjoint (a tenth
    held out as `choice_golden` by the stable hash of the RECORD id, so the split never
    moves between exports), scrubbed (the context is user text and goes through the PII
    seam; the options are platform-declared vocabulary — tool names, route names,
    declared definitions — and are exported as the decider saw them).

    Rows whose label is -1 (the decider picked none of the listed options) are excluded
    by `list_for_export`: they are real records worth keeping, but a selection corpus
    needs a selected option. Returns `{site: {"choice": node, "golden": node}}`.
    """
    from aughor.learning.decisions import list_for_export, sites

    out: dict[str, dict] = {}
    for s in ([site] if site else sites()):
        records = list_for_export(s)
        seen: set[str] = set()
        train_rows, golden_rows = [], []
        train_ids, golden_ids = [], []
        for r in records:
            example = {"context": _scrub(r["context"]), "options": r["options"],
                       "label": r["label"], "task": f"{task}:{s}"}
            key = hashlib.sha256(json.dumps(
                [example["context"], example["options"], example["label"]],
                sort_keys=True).encode("utf-8")).hexdigest()
            if key in seen:
                continue          # duplicates add weight, not signal — same as _dedupe
            seen.add(key)
            if _is_golden({"id": r["id"]}):
                golden_rows.append(example); golden_ids.append(r["id"])
            else:
                train_rows.append(example); train_ids.append(r["id"])
        out[s] = {
            "choice": store.register(
                f"decisions-{s}", "choice", train_rows, task=f"{task}:{s}",
                lineage=[("decision_record", i) for i in train_ids]),
            "golden": store.register(
                f"decisions-{s}-golden", "choice_golden", golden_rows, task=f"{task}:{s}",
                lineage=[("decision_record", i) for i in golden_ids]),
        }
    return out


def gate_status(org_id: Optional[str] = None) -> dict:
    """Where the corpus stands against MI-4's ENTRY GATES — measured, not estimated.

    MI-4 does not start until these pass; publishing the distance is what keeps the arc
    falsifiable rather than aspirational (§3.9's falsifier: if the graded-pair rate cannot
    plausibly reach these in ~90 days, the distillation premise is unproven HERE)."""
    gates = {"sft": 1000, "dpo": 150, "golden": 150}
    s = store.stats(org_id=org_id)
    out: dict = {
        kind: {"have": s.get(kind, {}).get("examples", 0), "need": need,
               "passes": s.get(kind, {}).get("examples", 0) >= need}
        for kind, need in gates.items()
    }
    # The fourth gate, which this report never checked (PENDING item 23): 30 days of guard data on real traffic.
    days = _guard_days(org_id)
    out["guard_days"] = {"have": days, "need": 30, "passes": days >= 30}
    # Tiers graded by execution or by a guard — reported, never counted toward a gate (§3.9: the corpus a model
    # trains on first is human-graded).
    for kind in ("sft_bronze", "dpo_repair"):
        out[kind] = {"have": s.get(kind, {}).get("examples", 0), "need": None, "passes": None,
                     "note": "not a gate — graded by execution or a guard, not a person"}
    return out


def _guard_days(org_id: Optional[str]) -> int:
    from datetime import datetime, timezone
    try:
        from aughor.security.audit import GuardVerdicts
        first = GuardVerdicts.first_live_fire(org_id=org_id)
        if not first:
            return 0
        start = datetime.fromisoformat(str(first).replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - start).days)
    except Exception as exc:  # noqa: BLE001 — an unreadable guard log reads as no days, never as a pass
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the guard log's first fire was unreadable; the gate reads 0 days", counter="learning.guard_days")
        return 0
