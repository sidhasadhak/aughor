"""Arc BC-3 · investigate, then compose (ROADMAP §3.67).

The user, 2026-10-29: *"let the LLMs use The Briefing as an open canvas to draw any element … everything with
citations and drill down possibilities … it should make sense right away to any user."*

After Arc BG measures the guide's checks for the range, ONE tool loop (`agent/tool_loop.run_tool_loop`, the loop the
Analyst and the dashboards' chat use) lets the model dig before it writes:

* ``breakdown`` — a check by any low-cardinality column of the table it is dated by, each segment against its own
  usual range (compiled; no model SQL);
* ``query`` — a SELECT it writes, through the Data Canvas's guarded door;
* ``compose`` — concluding: the edition as blocks. Code validates it and gates every word; what fails goes back
  ONCE as sentences, and on the second attempt what still fails is left out and listed.

A floor figure the page left out is added by code. The loop runs under the Briefer's budget; a model that runs out
leaves an edition drawn by code from what was measured, which says so. Opening never runs any of this.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from aughor.briefing.compose import sources as S
from aughor.briefing.compose import spec as P

#: The model's steps (tool calls and the compose) and the SELECTs it may write, per edition.
MAX_STEPS = 7
MAX_QUERIES = 8
#: How many measured checks the model is shown in full, furthest from usual first.
MAX_SHOWN = 16


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", s.lower()).strip("_") or "query"

_SYSTEM = """\
You write one edition of a company's Briefing for ONE reader — the first thing they read about how the business did
in the range. It must make sense to them at once.

First INVESTIGATE, then COMPOSE.
- You are given every check the platform measured for the range: its value, the range before, a year earlier, its
  usual range (the ranges before, mean give or take one standard deviation), how far outside usual it sits (z), its
  streak. News is what left its usual range; a figure inside it is not news, whatever its change on last range.
- For the two or three moves that matter most to this reader, find WHERE and WHO: call breakdown (a check by a
  column) or query (a SELECT you write, on the schema given) until the move is explained — which customers, which
  storefront, which product, since when. Stop when you can say it plainly. You may call tools at most {queries}
  times for queries and {steps} steps in all.
- Then call compose ONCE with the blocks.

How to compose:
- The first block is the lead: the range's answer in one or two sentences a newcomer understands.
- Then choose, for each finding, the block whose SHAPE fits it: a bridge for where a total came from, a comparison
  for segments against their usual, a table for the specific orders or items, a map for countries, small multiples
  for the same measure across devices or channels, a heat grid for two-way breakdowns, a line for a level shift, a
  control when the reader will want to look at one segment at a time, a decision only when one is warranted, a
  quiet line for what held steady. A quiet range gets a short edition. At most 14 blocks.
- Every number in your words must come from a source, written as given (rounding allowed), and cited as
  {{words|source_id}} in lead, quiet and decision text. Never compute a new number.
- Never write that one thing caused, drove, lifted or was behind another, and never predict.
- Every figure marked floor must appear in a block (a figure block reading it is enough).

Block types (fields per type):
{types}"""


def breakdown_columns(conn_id: str, table: str, *, limit: int = 12) -> list[str]:
    """The columns a check dated by ``table`` can be broken down by: low-cardinality, not a key, not a date."""
    try:
        from aughor.semantic.metric_time import bare_name
        from aughor.tools.profile_cache import merged_profile_entry
        entry = merged_profile_entry(conn_id) or {}
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the profile is unreadable; checks are broken down by their declared dimensions only",
                 counter="briefing.compose.profile")
        return []
    want = bare_name(table)
    out = []
    for key, prof in (entry.get("columns") or {}).items():
        if not isinstance(prof, dict):
            continue
        if bare_name(str(prof.get("table") or str(key).split(".", 1)[0])) != want:
            continue
        dtype = str(prof.get("dtype") or "").lower()
        distinct = prof.get("distinct_count")
        if prof.get("is_fk") or prof.get("is_pk") or "date" in dtype or "time" in dtype:
            continue
        if prof.get("is_low_cardinality") or (isinstance(distinct, (int, float)) and 1 < distinct <= 50):
            out.append(str(prof.get("column") or str(key).split(".", 1)[-1]))
    return out[:limit]


def _dated_table(m: Any) -> str:
    col = str((m.get("time_column") if isinstance(m, dict) else getattr(m, "time_column", "")) or "")
    if "." in col:
        return col.split(".", 1)[0]
    tables = list((m.get("tables") if isinstance(m, dict) else getattr(m, "tables", [])) or [])
    return tables[0] if tables else ""


def _question(guide, reader, block: dict, figures: list[dict], sources: dict, columns: dict, floor: list[str],
              schema_text: str, period: str, coming: list[dict]) -> str:
    from aughor.briefing.edition import score

    watch = set(reader.check_ids)
    ranked = sorted(figures, key=lambda f: -score(f, watched=f["id"] in watch))[:MAX_SHOWN]
    payload = {
        "range": {"covers": block.get("covers"), "compared_with": block.get("compared_with"),
                  "a_year_earlier": block.get("last_year_label"),
                  "what_this_range_is_for_here": getattr(guide.ranges, period, "") or ""},
        "the_business": guide.business,
        "reader": {"name": reader.name, "watches": reader.watches, "watched_checks": sorted(watch)},
        "read_with_care": [c.text for c in guide.care],
        "fair_comparisons": [c.text for c in guide.comparisons],
        "floor": floor,
        "coming_up": [c["line"] for c in coming],
        "checks": [{**S.for_model(sources[f["id"]], max_rows=12), "why_it_matters": f.get("why") or "",
                    "better": f.get("better"), "breakdown_columns": columns.get(f["id"], [])} for f in ranked],
    }
    return json.dumps(payload, default=str, ensure_ascii=False) + "\n\nSCHEMA (for query):\n" + schema_text


def _compose_params() -> dict:
    s = {"type": "string"}
    arr = {"type": "array", "items": {"type": "string"}}
    block = {"type": "object", "required": ["type"], "properties": {
        "id": s, "type": {"type": "string", "enum": list(P.TYPES)}, "kicker": s, "title": s, "text": s, "sub": s,
        "source": s, "chain": arr, "label": s, "value": s, "compare": s, "series": s, "x": s, "columns": arr,
        "link": s, "column": s, "listens": s, "actions": arr,
        "mark": {"type": "object", "properties": {"at": s, "text": s}}}}
    return {"type": "object", "required": ["blocks"], "properties": {"blocks": {"type": "array", "items": block}}}


def code_edition(figures: list[dict], floor: list[str], why: str) -> dict:
    """An edition drawn by code from what was measured — when the model did not finish. Says so."""
    from aughor.briefing.edition import score
    ranked = sorted(figures, key=lambda f: -score(f, watched=False))
    ids = list(dict.fromkeys(floor + [f["id"] for f in ranked[:6]]))
    blocks = [P.Block(id=f"figure_{i}", type="figure", source=fid, by_code=True) for i, fid in enumerate(ids)]
    return {"blocks": blocks, "withheld": [], "left_out": [], "drawn_by_code": why}


def compose(conn_id: str, spec, *, scope_key: str, schema: Optional[str] = None, reader_id: str = "",
            llm=None, runner=None, run_query=None) -> dict:
    """Measure, investigate, compose, check — and keep the edition per reader. Raises LookupError with no guide."""
    from aughor.briefing import edition as E
    from aughor.briefing import guide as G
    from aughor.briefing import ranges, versions
    from aughor.kernel import metering
    from aughor.knowledge import period_brief
    from aughor.knowledge.briefing import keep_entry
    from aughor.orgsettings import figure_currency

    guide, rev = G.current(conn_id, schema)
    if guide is None:
        raise LookupError("this dataset has no Briefing guide yet — draft it first")
    published = bool(rev and rev.is_published)
    reader = E.resolve_reader(guide, reader_id)
    block = ranges.range_block(spec)
    period = spec.period if spec.period in ("day", "week", "month", "year") else "custom"
    currency = figure_currency(conn_id, schema)
    metrics_by_name = {m.name: m for m in ranges.governed_metrics(conn_id, schema)}
    usual_n = guide.news.usual_for(period)
    counts = {"queries": 0, "compose": 0, "steps": 0}
    stop_reason = ""
    token = metering.start() if metering.current() is None else None
    btoken = None
    try:
        try:
            from aughor.kernel.agents import effective_governance
            from aughor.workspace.store import workspace_for_connection
            gov = effective_governance("briefer", workspace_for_connection(conn_id))
            btoken = metering.set_budget(gov.token_budget, gov.time_budget_s)
        except Exception as exc:  # noqa: BLE001 — an unreadable budget never stops an edition; it is said
            from aughor.kernel.errors import tolerate
            tolerate(exc, "the Briefer's budget is unreadable; the edition runs under the step limit only",
                     counter="briefing.compose.budget")
        with (runner or (lambda: period_brief.connection_runner(conn_id)))() as (run_sql, dialect):
            measured = E.measure_edition(conn_id, spec, guide, published=published, run_sql=run_sql,
                                         dialect=dialect, schema=schema, currency=currency)
            figures = measured["figures"]
            for f in figures:
                f["name"] = f["label"]
            sources: dict[str, S.Source] = {f["id"]: S.from_check(f, period_word=period) for f in figures}
            columns: dict[str, list[str]] = {}
            for check in guide.checks:
                m, _why = E.measurable(check, metrics_by_name)
                if m is not None:
                    columns[check.id] = list(dict.fromkeys(list(check.dimensions)
                                                           + breakdown_columns(conn_id, _dated_table(m))))
            outcome: dict = {}

            def t_breakdown(args: dict) -> dict:
                counts["steps"] += 1
                check = guide.check(str(args.get("check_id") or ""))
                if check is None:
                    return {"error": f"no check is called {args.get('check_id')!r}"}
                m, why = E.measurable(check, metrics_by_name)
                if m is None:
                    return {"error": why}
                column = str(args.get("column") or "")
                sid = f"{check.id}_by_{column}".lower()
                src = S.breakdown(sid, f"{check.label} by {column.replace('_', ' ')}", m, column, spec,
                                  usual_n=usual_n, run_sql=run_sql, dialect=dialect, unit=check.unit,
                                  better=check.better, check_id=check.id)
                sources[sid] = src
                return S.for_model(src)

            def t_query(args: dict) -> dict:
                counts["steps"] += 1
                if counts["queries"] >= MAX_QUERIES:
                    return {"error": f"the {MAX_QUERIES} queries this edition may run are spent — compose now"}
                counts["queries"] += 1
                sid = _slug(str(args.get("id") or f"query_{counts['queries']}"))
                src = S.query(sid, str(args.get("label") or sid), conn_id, str(args.get("sql") or ""),
                              purpose=str(args.get("purpose") or ""), schema=schema, run=run_query)
                sources[sid] = src
                return S.for_model(src)

            def t_compose(args: dict) -> dict:
                counts["compose"] += 1
                try:
                    draft = P.Spec(blocks=[P.Block.model_validate(b) for b in args.get("blocks") or []])
                except Exception as exc:  # noqa: BLE001 — a malformed spec is refused back with why
                    return {"refused": [f"the blocks do not read: {exc}"[:400]]}
                blocks, refusals = P.validate(draft, sources)
                kept, withheld, held = P.gate(blocks, sources)
                if (refusals or held) and counts["compose"] < 2:
                    return {"refused": refusals + held,
                            "instruction": "fix these and call compose again with the whole edition"}
                if not kept:
                    return {"refused": refusals + held + ["nothing in the edition can be shown"]}
                outcome.update(blocks=kept, withheld=withheld, left_out=refusals)
                return {"concluded": True, "answer": "composed"}

            tools = [
                _tool("breakdown", "Break a check down by a column of the table it is dated by: each value against "
                      "its own usual range, furthest from usual first. No SQL needed.",
                      {"type": "object", "required": ["check_id", "column"],
                       "properties": {"check_id": {"type": "string"}, "column": {"type": "string"}}}, t_breakdown),
                _tool("query", "Run one SELECT you write on the schema given (read-only, guarded). Give it an id, "
                      "a label a reader understands and the purpose in one line. Use it for what breakdown cannot "
                      "answer: the largest orders, two columns at once, a join.",
                      {"type": "object", "required": ["id", "label", "sql", "purpose"],
                       "properties": {k: {"type": "string"} for k in ("id", "label", "sql", "purpose")}}, t_query),
                _tool("compose", "Write the edition: the blocks, in order. Ends the work.", _compose_params(),
                      t_compose, concludes=True),
            ]
            if llm is None:
                from aughor.llm.provider import get_provider
                llm = get_provider("coder")
            from aughor.business_profile.infer import gather_context
            from aughor.agent.tool_loop import run_tool_loop
            schema_text = gather_context(conn_id, schema)[0]
            system = _SYSTEM.format(queries=MAX_QUERIES, steps=MAX_STEPS,
                                    types="\n".join(f"- {k}: {v}" for k, v in P.TYPES.items()))
            question = _question(guide, reader, block, figures, sources, columns, measured["floor"], schema_text,
                                 period, E.coming_up(guide, spec))
            try:
                result = run_tool_loop(llm, system, question, tools, max_steps=MAX_STEPS, conn_id=conn_id,
                                       site="briefing.compose")
                stop_reason = result.stop_reason
            except metering.BudgetExceeded as exc:
                stop_reason = f"the Briefer's budget ran out ({exc})"
            composed = outcome or code_edition(figures, measured["floor"],
                                               f"the model did not finish the edition ({stop_reason or 'no answer'})")
    finally:
        if btoken is not None:
            metering.clear_budget(btoken)
        if token is not None:
            metering.reset(token)

    told = {sid for b in composed["blocks"] for sid in P.sources_of(b)}
    for fid in measured["floor"]:
        if fid not in told:
            composed["blocks"].append(P.Block(id=f"floor_{fid}", type="figure", source=fid, by_code=True,
                                              kicker="Also outside its usual range"))
    used = {sid for b in composed["blocks"] for sid in P.sources_of(b)}
    entry = {"edition": True, "composed": True, "spec_version": P.VERSION,
             "blocks": [b.model_dump(mode="json") for b in composed["blocks"]],
             "sources": {sid: src.model_dump(mode="json") for sid, src in sources.items()
                         if sid in used or src.kind != "check"},
             "withheld": composed.get("withheld", []), "left_out": composed.get("left_out", []),
             "drawn_by_code": composed.get("drawn_by_code", ""),
             "reader": {"group_id": reader.group_id, "name": reader.name},
             "guide": {"version": rev.version if rev else None, "state": rev.state if rev else None},
             "period": {**block, "measured": figures}, "not_read": measured["not_read"], "floor": measured["floor"],
             "generated_at": datetime.now(timezone.utc).isoformat(), "currency_code": currency,
             "model_steps": counts["steps"] + counts["compose"], "queries": counts["queries"],
             "stop_reason": stop_reason}
    keep_entry(E.cache_key(scope_key, spec, reader.group_id), entry)
    entry["version"] = versions.record(conn_id, entry, scope_key=scope_key, range_key=spec.key,
                                       recipe=f"edition@{reader.group_id or '_organisation'}")
    return entry


def _tool(name: str, description: str, parameters: dict, run, *, concludes: bool = False):
    from aughor.agent.tool_loop import ToolSpec
    return ToolSpec(name=name, description=description, parameters=parameters, run=run, concludes=concludes)


def sheet_lines(entry: dict) -> list[tuple[str, list[str]]]:
    """An edition as the lines a send departs with — every block's words, each judged at the departure gate
    against the sources re-run at the send."""
    prose: list[str] = []
    for b in entry.get("blocks") or []:
        words = " ".join(P.plain(x) for x in (b.get("title"), b.get("text"), b.get("sub")) if x)
        if words.strip():
            prose.append(words.strip())
    return [("narrative", prose)] if prose else []


# ── BC-4 · a drill, written into the page ────────────────────────────────────────────────────

def _literal(v: Any) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def drill(conn_id: str, spec, *, scope_key: str, schema: Optional[str] = None, reader_id: str = "",
          source_id: str, column: str, segment: Any = None, after: str = "", runner=None) -> dict:
    """One level deeper on a block's source: the same check broken down by ``column`` — within ``segment`` of the
    source's own breakdown when one is named — compiled, no model. Written into the kept edition under the block
    ``after`` (or at the end), so everyone reading the edition sees it. Raises LookupError / ValueError with why."""
    from aughor.briefing import edition as E
    from aughor.briefing import guide as G
    from aughor.briefing import ranges
    from aughor.knowledge import period_brief
    from aughor.knowledge.briefing import keep_entry, peek_entry

    key = E.cache_key(scope_key, spec, reader_id)
    entry = peek_entry(key)
    if not (isinstance(entry, dict) and entry.get("composed")):
        raise LookupError("this edition has not been written yet")
    raw = (entry.get("sources") or {}).get(source_id)
    if raw is None:
        raise LookupError(f"this edition has no source {source_id!r}")
    src = S.Source.model_validate(raw)
    if src.kind == "check":
        check_id, within = src.id, {}
    elif src.kind in ("breakdown", "drill"):
        check_id, within = str(src.facts.get("check") or ""), dict(src.facts.get("within") or {})
        if segment is not None:
            within[str(src.facts.get("by"))] = segment
    else:
        raise ValueError("only a check or a breakdown can be drilled; a written query is not compiled from one")
    if not column.isidentifier() or not all(str(k).isidentifier() for k in within):
        raise ValueError("a drill names a column")
    guide, _rev = G.current(conn_id, schema)
    check = guide.check(check_id) if guide else None
    if check is None:
        raise LookupError(f"the guide no longer has the check {check_id!r}")
    m, why = E.measurable(check, {mm.name: mm for mm in ranges.governed_metrics(conn_id, schema)})
    if m is None:
        raise ValueError(why)
    for col, val in within.items():
        cond = f"{col} = {_literal(val)}"
        filters = list(m.get("filters") if isinstance(m, dict) else getattr(m, "filters", []) or []) + [cond]
        m = {**m, "filters": filters} if isinstance(m, dict) else m.model_copy(update={"filters": filters})
    words = " and ".join(f"{k.replace('_', ' ')} {v}" for k, v in within.items())
    label = f"{check.label} by {column.replace('_', ' ')}" + (f", within {words}" if words else "")
    sid = _slug(f"{check.id}_{'_'.join(str(v) for v in within.values())}_by_{column}")
    usual_n = guide.news.usual_for(spec.period if spec.period in ("day", "week", "month", "year") else "custom")
    with (runner or (lambda: period_brief.connection_runner(conn_id)))() as (run_sql, dialect):
        new = S.breakdown(sid, label, m, column, spec, usual_n=usual_n, run_sql=run_sql, dialect=dialect,
                          unit=check.unit, better=check.better, kind="drill", check_id=check.id, within=within)
    if new.error:
        raise ValueError(new.error)
    block = P.Block(id=f"drill_{sid}", type="compare", source=sid, kicker="Drill", title=label + ", against usual",
                    by_code=True)
    blocks = list(entry.get("blocks") or [])
    at = next((i + 1 for i, b in enumerate(blocks) if b.get("id") == after), len(blocks))
    blocks.insert(at, block.model_dump(mode="json"))
    entry = {**entry, "blocks": blocks, "sources": {**(entry.get("sources") or {}), sid: new.model_dump(mode="json")}}
    keep_entry(key, entry)
    return {"block": block.model_dump(mode="json"), "source": new.model_dump(mode="json"), "at": at}
