"""GM-2 — the census is a ratchet (ROADMAP §3.49; `docs/GATE_MAP_STUDY_2026-09-26.md` §2).

Every place SQL reaches a warehouse goes through the door, and every one of them says how the statement's dialect is
handled — declared to the door, written for the engine by its author, rendered in the engine's dialect, portable,
or not handled at all. The study measured that once, by hand, and a measurement with a timestamp rots: GM-1's own
build found nine sites the study's census had missed. So the census is now `docs/SQL_DOORS.json`, and this test
holds the code to it:

* the WALK finds every door call in `aughor/` — the population comes from the code, never from the file, so a new
  call fails here with the row to add;
* a row whose site is gone fails too, so the file cannot drift into a list of things that used to be true;
* where the code can say the classification itself, the code is the authority: a call that declares
  ``sql_dialect="duckdb"`` is classified `declared` and nothing else, and a `declared` row whose call stopped
  declaring fails;
* the bug class (`none`) and the model SQL written with no dialect stated (`unstated`) may only fall — each count is
  pinned exactly, so a fix lowers the baseline in the same change and a regression cannot hide in slack.

A site is keyed by where it is and what it says, never by its line: ``path::enclosing function::door::label``, with a
``#n`` ordinal when one function holds the same door and label more than once. Keys survive unrelated edits; a
renamed function or label moves its row, which is the point.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CENSUS = REPO / "docs" / "SQL_DOORS.json"

#: How a site's statement meets the engine's dialect — one definition, shared with the gate map a
#: person reads (`aughor/govern/gate_map.py`, `GET /governance/gate-map`).
from aughor.govern.gate_map import DIALECTS  # noqa: E402

AUTHORS = {"platform", "model", "person", "stored", "door", "mixed"}

#: The two counts that may only fall. Lower each in the same change that lowers its count — never raise it.
#: 2026-09-29 (GM-2): measured at the census's first cut, after GM-1 and the nine sites it found.
#: 2026-10-04: `none` 3 → 2 — the overview tour's probes declare their dialect; `unstated` 5 → 4 — the
#: conversation agent is told its engine; 4 → 0 the same day — the explore planner and the ontology
#: enricher's formulas are told theirs.
NONE_BASELINE = 2
UNSTATED_BASELINE = 0

# ── the walk ──────────────────────────────────────────────────────────────────────────────────────────────────────────

#: The door's methods. `execute` is shared with every driver and SQLite store, so an `execute` call is told apart by
#: its shape: the door is `execute(label, sql)`, a driver `execute(sql)` or `execute(sql, params)`.
DOORS = {"execute", "execute_bounded", "execute_typed", "execute_with_params", "execute_with_params_typed",
         "read_typed_rows", "rows", "scalar", "bulk_read", "execute_guarded"}
_SQL_START = re.compile(r"\s*(SELECT|WITH|PRAGMA|CREATE|INSERT|UPDATE|DELETE|DROP|ALTER|BEGIN|COMMIT|ROLLBACK|VACUUM|"
                        r"REPLACE|ATTACH|DETACH|SET|LOAD|INSTALL|USE|DESCRIBE|SHOW|EXPLAIN|SUMMARIZE|COPY|CHECKPOINT|"
                        r"ANALYZE|CALL|FROM)\b", re.I)
#: A driver's bind parameters, by the names this codebase gives them.
_PARAM_NAMES = {"params", "args", "_params", "bind_params", "row", "values", "vals", "binds", "parameters",
                "investigation_ids", "data", "bindings"}
#: A driver's statement, by the names this codebase gives it when it comes first.
_SQL_NAMES = {"sql", "q", "query", "stmt", "translated", "ddl"}


def _text(node) -> str:
    """The literal text of a str constant, an f-string or a `+` concatenation, placeholders dropped."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _text(node.left) + _text(node.right)
    return ""


def _terminal(node) -> str:
    return node.id if isinstance(node, ast.Name) else (node.attr if isinstance(node, ast.Attribute) else "")


def _is_door_call(call: ast.Call, name: str) -> bool:
    """Whether a call of a door-named method reaches the SQL door, rather than a driver or a SQLite store."""
    args = call.args
    if name in ("rows", "scalar"):
        return bool(args) and not isinstance(args[0], ast.Dict)    # `processes.rows(query)` is the object API
    if name in ("bulk_read",):
        return bool(args)
    if name != "execute":
        return len(args) >= 2
    if any(kw.arg == "query_id" for kw in call.keywords):
        return True                          # an injected `execute_guarded`
    if len(args) < 2:
        return False
    a0, a1 = args[0], args[1]
    literal = _text(a0)
    if isinstance(a0, (ast.Constant, ast.JoinedStr, ast.BinOp)) and literal:
        # a label never holds whitespace; a statement nearly always does
        return not (_SQL_START.match(literal) or re.search(r"\s", literal))
    if isinstance(a1, (ast.Tuple, ast.List, ast.Dict, ast.Set, ast.ListComp, ast.IfExp, ast.GeneratorExp)):
        return False
    if isinstance(a1, ast.Call) and _terminal(a1.func) in ("tuple", "list", "dict", "_adapt_params"):
        return False
    if _terminal(a1) in _PARAM_NAMES or _terminal(a0) in _SQL_NAMES:
        return False
    return not (isinstance(a0, ast.Call) and _terminal(a0.func) in ("render_for_engine", "translate"))


def _declaration(call: ast.Call) -> str:
    """'declared' when the call declares DuckDB, 'forwards' when it passes on a declaration it was given, else ''."""
    for kw in call.keywords:
        if kw.arg == "sql_dialect":
            if isinstance(kw.value, ast.Constant):
                return "declared" if kw.value.value == "duckdb" else ""
            return "forwards"
    if any(isinstance(a, ast.Call) and _terminal(a.func) == "sql_for_engine" for a in call.args):
        return "forwards"
    return ""


def _internal(call: ast.Call, name: str) -> str:
    """GM-5 — 'internal' when the call declares its statement the platform's own, 'forwards' when it passes on a
    declaration it was given, else ''. `read_typed_rows` is plumbing by definition and declares itself."""
    if name == "read_typed_rows":
        return "internal"
    for kw in call.keywords:
        if kw.arg == "internal":
            if isinstance(kw.value, ast.Constant):
                return "internal" if kw.value.value is True else ""
            return "forwards"
    return ""


def _label(call: ast.Call, name: str, src: str) -> str:
    keyword = {"rows": "label", "scalar": "label", "execute_guarded": "query_id"}.get(name)
    if name == "execute" and any(kw.arg == "query_id" for kw in call.keywords):
        keyword = "query_id"
    if name == "bulk_read":
        return "__bulk__"
    if keyword:
        node = next((kw.value for kw in call.keywords if kw.arg == keyword), None)
        if node is None:
            return "__adapter__" if name in ("rows", "scalar") else "?"
    else:
        node = call.args[0]
    if isinstance(node, ast.Constant):
        return str(node.value)
    return "{" + " ".join((ast.get_source_segment(src, node) or "?").split())[:60] + "}"


class _Walk(ast.NodeVisitor):
    def __init__(self, src: str):
        self.src, self.scope, self.sites = src, [], []

    def _scoped(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scoped

    def visit_Call(self, node: ast.Call):
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
        if name in DOORS and _is_door_call(node, name):
            self.sites.append((".".join(self.scope) or "<module>", name, _label(node, name, self.src),
                               node.lineno, _declaration(node), _internal(node, name)))
        self.generic_visit(node)


def door_sites() -> dict[str, dict]:
    """Every door call under `aughor/`, keyed as the census keys it."""
    out: dict[str, dict] = {}
    for path in sorted((REPO / "aughor").rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        src = path.read_text(encoding="utf-8")
        walk = _Walk(src)
        walk.visit(ast.parse(src))
        seen: dict[str, int] = {}
        for where, door, label, line, declared, internal in walk.sites:
            base = f"{rel}::{where}::{door}::{label}"
            seen[base] = seen.get(base, 0) + 1
            out[base if seen[base] == 1 else f"{base}#{seen[base]}"] = {"line": line, "machine": declared,
                                                                        "internal": internal}
    return out


# ── the census ────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def sites() -> dict[str, dict]:
    return door_sites()


@pytest.fixture(scope="module")
def census() -> dict[str, dict]:
    return json.loads(CENSUS.read_text(encoding="utf-8"))["sites"]


def test_the_walk_finds_the_doors(sites):
    """A walk that found nothing would pass every test below. These sites are the study's own examples."""
    for key in ("aughor/sql/join_guard.py::_probe_overlap::execute::__domain_probe__",
                "aughor/monitors/runner.py::_query::rows::__monitor__",
                "aughor/routers/query.py::_query_run._work::execute::{_source}",
                "aughor/agent/investigate.py::_execute_safe::execute_guarded::{phase_id}",
                "aughor/semantic/metrics.py::compute_value::execute::__metric_value__"):
        assert key in sites, f"the walk no longer finds {key}"
    assert len(sites) > 150, f"the walk found {len(sites)} door calls; the study counted 150 warehouse sites"


def test_every_site_is_classified(sites, census):
    missing = sorted(set(sites) - set(census))
    rows = [
        f'    "{key}": {{"dialect": "{sites[key]["machine"] or "<one of: " + ", ".join(sorted(set(DIALECTS) - {"declared", "forwards"})) + ">"}", '
        f'"author": "<{"|".join(sorted(AUTHORS))}>"}},   # line {sites[key]["line"]}'
        for key in missing
    ]
    assert not missing, (
        f"{len(missing)} door call(s) with no row in docs/SQL_DOORS.json. Say how each one's dialect is handled — "
        "declare sql_dialect='duckdb' if the platform wrote it in DuckDB's spelling — and add:\n" + "\n".join(rows))


def test_no_row_outlives_its_site(sites, census):
    stale = sorted(set(census) - set(sites))
    assert not stale, (
        "rows in docs/SQL_DOORS.json whose call is gone, or whose function or label was renamed — move or remove "
        "them:\n" + "\n".join(f"    {key}" for key in stale))


def test_every_row_uses_the_census_words(census):
    bad = {k: v for k, v in census.items()
           if v.get("dialect") not in DIALECTS or v.get("author") not in AUTHORS}
    assert not bad, f"unknown dialect or author (dialects {sorted(DIALECTS)}, authors {sorted(AUTHORS)}): {bad}"
    unexplained = sorted(k for k, v in census.items()
                         if v["dialect"] in ("none", "unstated", "not-sql") and len(v.get("note", "")) < 20)
    assert not unexplained, f"a {'/'.join(('none', 'unstated', 'not-sql'))} row must say why in its note: {unexplained}"


def test_the_code_is_the_authority_where_it_can_speak(sites, census):
    """`declared` and `forwards` are read off the call. A row cannot claim them for a call that does not, and a call
    that declares cannot be filed under any other class."""
    wrong = {key: (census[key]["dialect"], sites[key]["machine"] or "(nothing)")
             for key in set(sites) & set(census)
             if (census[key]["dialect"] in ("declared", "forwards") or sites[key]["machine"])
             and census[key]["dialect"] != sites[key]["machine"]}
    assert not wrong, ("rows that disagree with the call they describe (row says, call says):\n"
                       + "\n".join(f"    {k}: {v}" for k, v in sorted(wrong.items())))


@pytest.mark.parametrize("dialect,baseline", [("none", NONE_BASELINE), ("unstated", UNSTATED_BASELINE)])
def test_the_bug_classes_only_fall(census, dialect, baseline):
    now = sorted(k for k, v in census.items() if v["dialect"] == dialect)
    assert len(now) <= baseline, (
        f"{len(now)} '{dialect}' sites against a baseline of {baseline} — a new site joined the class. Fix it "
        f"instead: {DIALECTS[dialect]}.\n" + "\n".join(f"    {k}" for k in now))
    assert len(now) == baseline, (
        f"only {len(now)} '{dialect}' sites remain — lower the baseline in {Path(__file__).name} to {len(now)} "
        "in this change, so the room cannot be spent on a regression later")


# ── GM-5: who may declare a statement the platform's own ────────────────────────────────────────────────────────────
#
# `internal=True` on a door call skips the safety check, the audit row and PII redaction. It used to be decided by how
# the label was spelled, and 21 statements a model, a person or a stored definition wrote were exempt by spelling alone.
# The call declares it now, and these hold the declaration to the row's `author`: the platform's own statements declare
# it; nobody else's may. An exception says why, in the row, where a reviewer reads it.

def test_only_the_platform_declares_its_statements_internal(sites, census):
    wrong = [f"    {key}   (author: {census[key]['author']})" for key in sorted(sites)
             if key in census and sites[key]["internal"] == "internal"
             and census[key]["author"] != "platform" and not census[key].get("internal")]
    assert not wrong, (
        f"{len(wrong)} door call(s) declare internal=True on a statement the platform did not write — it skips the "
        "safety check, the audit row and PII redaction. Drop the declaration, or say why in the row's `internal` "
        "field:\n" + "\n".join(wrong))


def test_the_platform_declares_its_own_statements(sites, census):
    missing = [f"    {key}" for key in sorted(sites)
               if key in census and census[key]["author"] == "platform" and census[key]["dialect"] != "not-sql"
               and not sites[key]["internal"] and not census[key].get("audited")]
    assert not missing, (
        f"{len(missing)} platform statement(s) with no internal=True — each lands on the audit page as somebody's "
        "activity. Declare it, or say why it is audited in the row's `audited` field:\n" + "\n".join(missing))


def test_an_exception_is_a_reason(census):
    for key, row in census.items():
        for field in ("internal", "audited"):
            if field in row:
                assert isinstance(row[field], str) and len(row[field].split()) >= 4, (
                    f"{key}: `{field}` is a reviewer's sentence saying why, not a flag")
        assert not ("internal" in row and "audited" in row), f"{key}: a row is an exception one way, not both"



def test_the_gate_map_a_person_reads_is_the_same_census(tmp_path, census):
    """`GET /governance/gate-map` serves this file grouped, names the unguarded sites, counts each
    departure law's holds — and says so when the census is not on the install."""
    from aughor.govern import gate_map as G
    seen = G.statement_doors()
    assert seen["present"] and seen["sites"] == len(census)
    assert sum(r["sites"] for r in seen["by_dialect"]) == seen["sites"] == sum(r["sites"] for r in seen["by_door"])
    assert len([s for s in seen["unguarded"] if s["dialect"] == "none"]) == NONE_BASELINE
    assert all(s["note"] for s in seen["unguarded"])                       # an unguarded site carries its reason
    assert all(r["means"] for r in seen["by_dialect"])
    absent = G.statement_doors(tmp_path / "nowhere.json")
    assert absent["present"] is False and "not on this install" in absent["note"] and absent["sites"] == 0
    laws = G.departure_laws()["laws"]
    from aughor.govern.departure import GUARDS
    assert [row["guard"] for row in laws] == list(GUARDS) and all(row["label"] for row in laws)
