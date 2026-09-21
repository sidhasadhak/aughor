"""A3 — the screen beside the approval ask.

A person is asked to approve a metric definition through ``POST /metrics/{name}/transition``
(`aughor/routers/metrics.py`). That route validates the lifecycle, persists the new state and
journals an audit event — and tells the approver NOTHING about what they are approving. This
module is the instrument beside the question: what changed, whether the definition can even be
executed and what it produces, on which population, and what the definition leaves undeclared.

**Advisory, never a gate.** The report never holds, refuses or blocks an approval — the
definition is the user's call. Nothing here imports `govern.guard`, `gate_departure` or
`blocking_caveats`, and `tests/unit/test_definition_report.py` asserts that the import graph
stays clean. Two readers of the drafting study independently recommended modelling this on
`govern.departure.Measurement`, whose `blocking_caveats` field HOLDS a send; following that
recommendation literally would have violated the one constraint this slice was given.

**The population is NOT frozen, and the report says so.** The drafting assumption was that
naming a fixed time window gives a reproducible population. Measured on the receipt target's own
warehouse, it does not, on three independent grounds:

* there is no way to pin a BigQuery population here — `db.snapshot.execute_as_of` is DuckLake-only
  (`as_of_supported` probes `duckdb_databases()`), and BigQuery's own ``FOR SYSTEM_TIME AS OF``
  appears nowhere in this tree;
* ``return_rate``'s numerator accrues IN PLACE — ``returned_at`` goes NULL → timestamp on rows
  already inside a closed window, so the same definition over the same named window yields a
  different number next month, by the metric's own ``wrong_usage_examples``;
* the drift token that would have noticed either, `db.snapshot.data_version`, returns ``None``
  silently on BigQuery, because `snapshot._quote` hard-codes double quotes that BigQuery parses
  as a STRING LITERAL — the failure `aughor/db/quoting.py` documents with this dataset by name.

So :class:`Population` carries a typed verdict — ``PINNED`` / ``FINGERPRINTED`` / ``UNPINNABLE``
— and an UNPINNABLE with no reason is a construction error rather than a quiet null. A field that
is permanently null and does not say why is the ``X or {}`` failure this repo has a standing rule
against: "the data did not move" and "nothing could tell me whether it moved" must not be one
value. Presenting two numbers as "the same population, scored two ways" when they are two reads
of a moving table would give the approver MORE confidence than a bare formula does, which is
worse than the screen it replaces.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

# ── Outcome vocabulary ────────────────────────────────────────────────────────
# Mirrors `govern.departure._Check`'s shape deliberately, MINUS every word that can stop
# something (`HOLDS`, `ASKED`, `EXEMPT`). An advisory report has no verdict that acts, and
# leaving those words unavailable is what stops a later edit from quietly growing one.
CLEAN = "clean"                    # checked, and there was nothing to report
FINDINGS = "findings"              # checked, and here is what it found
NOT_APPLICABLE = "not_applicable"  # there was nothing of this kind to check
UNAVAILABLE = "unavailable"        # could NOT check, and the reason says why

#: Severities. Neither one blocks; the distinction is what a reader should do about it.
DEFECT = "defect"    # the definition is wrong or cannot run as written
CAUTION = "caution"  # the definition runs, but a reader should know this before approving

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Finding:
    """One thing worth the approver's eye, with the measurement that produced it.

    ``evidence`` is not decoration: a finding a reader cannot check is a finding they must
    take on faith, and this screen exists precisely to stop an approval resting on faith.
    """

    code: str        # stable slug — the thing a test asserts on, never the prose
    severity: str    # DEFECT | CAUTION
    what: str        # one sentence, shown verbatim
    evidence: str    # the specific measured fact behind it

    def __post_init__(self) -> None:
        if self.severity not in (DEFECT, CAUTION):
            raise ValueError(f"unknown severity {self.severity!r}")
        if not self.evidence.strip():
            raise ValueError(f"finding {self.code!r} carries no evidence")


@dataclass(frozen=True)
class Claim:
    """One section of the report — its outcome, a sentence, and what it found.

    ``UNAVAILABLE`` with an empty summary is refused at construction. "I checked and found
    nothing" and "I could not check" are different answers, and a shape that lets them collapse
    into one is the defect this class exists to prevent.
    """

    outcome: str
    summary: str
    findings: tuple[Finding, ...] = ()
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.outcome not in (CLEAN, FINDINGS, NOT_APPLICABLE, UNAVAILABLE):
            raise ValueError(f"unknown outcome {self.outcome!r}")
        if self.outcome == UNAVAILABLE and not self.summary.strip():
            raise ValueError("an UNAVAILABLE claim must say why it could not be checked")
        if self.outcome == FINDINGS and not self.findings:
            raise ValueError("a FINDINGS claim must carry at least one finding")


# ── The population ────────────────────────────────────────────────────────────
PINNED = "pinned"              # reproducible AT a past version (DuckLake time travel)
FINGERPRINTED = "fingerprinted"  # not pinned, but drift is detectable after the fact
UNPINNABLE = "unpinnable"      # neither — and `reason` says what is missing


@dataclass(frozen=True)
class Population:
    """What the numbers in this report were read from, and how reproducible that is.

    This is the field the drafting study asked A4 to store and A4 never shipped: A4 landed
    `Measurement.caveats` and `blocking_caveats`, and the scope half — "store the measurement's
    scope in the artifact, and make any chart that spans rounds say that it excluded rows
    measured under a retired scope" — has no field, no test and no consumer anywhere in the
    tree. The roadmap marks A4 ✅ and A3 "Needs A4", so a reader would reasonably assume this
    existed. It did not, so it is defined here.
    """

    mode: str
    reason: str = ""        # REQUIRED when UNPINNABLE — never a silent null
    token: str = ""         # the snapshot id or fingerprint, when there is one
    tables: tuple[str, ...] = ()
    taken_at: str = ""

    def __post_init__(self) -> None:
        if self.mode not in (PINNED, FINGERPRINTED, UNPINNABLE):
            raise ValueError(f"unknown population mode {self.mode!r}")
        if self.mode == UNPINNABLE and not self.reason.strip():
            raise ValueError("an UNPINNABLE population must carry the reason it cannot be pinned")
        if self.mode in (PINNED, FINGERPRINTED) and not self.token.strip():
            raise ValueError(f"a {self.mode} population must carry its token")

    @property
    def reproducible(self) -> bool:
        """True only when this exact read can be taken again. FINGERPRINTED is NOT reproducible
        — it can only tell you afterwards that something moved."""
        return self.mode == PINNED


@dataclass(frozen=True)
class DefinitionReport:
    """The whole screen, as data. Rendered beside the approval ask; never consulted by a gate."""

    metric: str
    connection_id: str
    status: str
    version: int
    predecessor: Claim     # what changed — or that there is nothing to change from
    execution: Claim       # whether it runs, and what it produced
    declaration: Claim     # what the definition leaves undeclared or contradicts
    segments: Claim        # what could be compared per-segment — usually nothing, honestly said
    population: Population
    taken_at: str = ""

    #: Never consulted by a gate. Present so a reader of the JSON knows it, and so a future
    #: edit that tries to make this authoritative has to delete a line that says not to.
    advisory: bool = True

    @property
    def findings(self) -> tuple[Finding, ...]:
        out: list[Finding] = []
        for c in (self.predecessor, self.execution, self.declaration, self.segments):
            out.extend(c.findings)
        return tuple(out)

    @property
    def defects(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == DEFECT)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_approved(metric: Any) -> bool:
    """Mirrors `govern.departure.metric_is_approved` deliberately rather than importing it.

    Importing it would pull `govern.departure` — and with it `gate_departure` and
    `blocking_caveats` — into this module's import graph, which is the one thing the
    advisory-only constraint forbids. Mirroring risks a second vocabulary drifting from the
    first, so `test_definition_report.py` asserts the two agree on every lifecycle state
    rather than trusting that they do.
    """
    status = str(getattr(metric, "status", "") or "")
    if status:
        return status == "approved"
    return bool(getattr(metric, "approved_by", None))


# ── The four claims ───────────────────────────────────────────────────────────

def predecessor_claim(metric: Any, audit_events: Sequence[Mapping[str, Any]] = ()) -> Claim:
    """What this definition is changing FROM.

    On the receipt target there is nothing: ``return_rate``'s audit trail is two delete events,
    both with ``sql: null`` — no create, propose, approve or reject has ever been recorded, and
    `semantic.governance` emits no ``sql`` field at all while `semantic.metrics.save_metric`
    overwrites the row in place. So a predecessor was never retained and could not be recovered.

    That is reported as NOT_APPLICABLE with a sentence, never as an empty diff: an empty diff
    panel and "nothing changed" are indistinguishable on screen, and they mean opposite things.
    First approval is also the COMMON case here, not an edge case worth degrading.
    """
    prior = [e for e in audit_events if (e or {}).get("sql")]
    if not prior:
        recorded = len(list(audit_events))
        return Claim(
            NOT_APPLICABLE,
            "First approval — there is no earlier definition to compare against."
            + (f" Its audit trail has {recorded} event(s), none carrying a formula."
               if recorded else " Nothing has been recorded against it."),
            detail={"audit_events": recorded, "with_formula": 0},
        )
    was = str(prior[0].get("sql") or "")
    now = str(getattr(metric, "sql", "") or "")
    if was.strip() == now.strip():
        return Claim(CLEAN, "The formula is unchanged since the last recorded version.",
                     detail={"sql": now})
    return Claim(
        FINDINGS, "The formula differs from the last recorded version.",
        findings=(Finding("formula_changed", CAUTION,
                          "The formula has changed since it was last recorded.",
                          f"was {was!r}, now {now!r}"),),
        detail={"was": was, "now": now},
    )


def execution_claim(metric: Any, db: Any) -> Claim:
    """Whether the definition runs at all, and what it produced.

    Goes through `semantic.metrics.compute_value`, NOT ``GET /metrics/{name}/value``. That route
    resolves the metric by NAME ALONE (no ``connection_id``), so on this deployment it answers
    ``revenue`` for theLook with the formula of a connection that no longer exists — a confident
    wrong number at HTTP 200 with nothing naming whose definition ran. `compute_value` takes the
    resolved definition and is already the typed verdict this needs: ``value=None, error=""`` is
    a healthy empty, ``error != ""`` is a failure, and it never raises.
    """
    if db is None:
        return Claim(UNAVAILABLE,
                     "No connection was open, so the definition was not executed.")
    from aughor.semantic.metrics import compute_value

    result = compute_value(metric, db)
    if result.error:
        return Claim(
            UNAVAILABLE,
            f"The definition could not be executed: {result.error}",
            detail={"sql": result.sql, "error": result.error},
        )
    if result.value is None:
        return Claim(
            FINDINGS, "The definition ran and matched no rows.",
            findings=(Finding("matched_no_rows", CAUTION,
                              "The definition executes but currently matches no rows.",
                              f"ran {result.sql!r}, no value"),),
            detail={"sql": result.sql, "value": None},
        )
    return Claim(CLEAN, f"The definition executes and currently reads {result.value:g}.",
                 detail={"sql": result.sql, "value": result.value})


def declaration_claim(metric: Any, table_cols: Optional[Mapping[str, Sequence[str]]] = None
                      ) -> Claim:
    """What the definition leaves undeclared, contradicts, or silently loses.

    Every check here is static — no warehouse call — so this claim is available even when the
    connection is unreachable, which is exactly when an approver most needs it.
    """
    findings: list[Finding] = []
    sql = str(getattr(metric, "sql", "") or "").strip()
    tables = tuple(getattr(metric, "tables", ()) or ())
    filters = tuple(getattr(metric, "filters", ()) or ())
    misuse = tuple(getattr(metric, "wrong_usage_examples", ()) or ())
    is_full_select = sql.lower().startswith("select")

    if not tables and not is_full_select:
        findings.append(Finding(
            "no_table_named", DEFECT,
            "The definition names no table, so the query it builds has no FROM clause.",
            f"tables=[] and the formula does not start with SELECT: {sql!r}"))

    # The silent one. `metrics.value_query` appends WHERE only INSIDE the `if metric.tables`
    # branch, so declared filters on a table-less metric are dropped without a word — and the
    # filters ARE the definition. Approving that ships a number the approver believes is
    # filtered and is not.
    if filters and not tables and not is_full_select:
        findings.append(Finding(
            "filters_silently_dropped", DEFECT,
            "The declared filters are dropped when the query is built, because no table is "
            "named — the number would be computed unfiltered.",
            f"filters={list(filters)} with tables=[]"))

    # A definition that documents a misuse it does not prevent. On the receipt target,
    # `wrong_usage_examples` says reading it over a population containing cancelled lines is
    # wrong, and `filters` is empty.
    if misuse and not filters:
        findings.append(Finding(
            "documented_caution_unenforced", CAUTION,
            "The definition documents a way of reading it that is wrong, but declares no "
            "filter that prevents it.",
            f"{len(misuse)} wrong-usage note(s), filters=[]"))

    # Undeclared grain. Only answerable with the schema in hand, and only interesting when the
    # definition names no table: a column carried by two tables means two different metrics.
    # Matching is by identifier TOKEN, never substring — a substring test would count `order`
    # as referenced on the strength of `order_id`.
    if table_cols and not tables and not is_full_select:
        referenced = {t.lower() for t in _IDENT.findall(sql)}
        for col in sorted(referenced):
            carriers = sorted(t for t, cols in table_cols.items()
                              if col in {str(c).lower() for c in cols})
            if len(carriers) > 1:
                findings.append(Finding(
                    "undeclared_grain", DEFECT,
                    f"'{col}' is carried by more than one table and the definition names "
                    f"none, so its grain is undeclared.",
                    f"{col} appears on {', '.join(carriers)}"))

    # Whether the grain question was ASKED at all. `table_cols` is optional because the HTTP
    # door cannot supply it: `routers/_shared.get_schema_cached` BUILDS on a cache miss, and a
    # read that builds is the defect that once hung `GET /ontology`. Recording the skip is the
    # point — a check that quietly does not run looks exactly like a check that found nothing,
    # and this report's whole job is keeping those two apart.
    grain_checked = bool(table_cols) and not tables and not is_full_select
    detail = {
        "grain_checked": grain_checked,
        "grain_skipped_because": (
            "" if grain_checked
            else "no schema was supplied, so columns carried by more than one table were not "
                 "looked for" if not table_cols
            else "the definition names its table, so its grain is declared"),
    }

    if not findings:
        return Claim(CLEAN, "The definition declares everything needed to build its query.",
                     detail=detail)
    return Claim(FINDINGS, f"{len(findings)} thing(s) about this definition need a reader's eye.",
                 findings=tuple(findings), detail=detail)


def segments_claim(metric: Any) -> Claim:
    """What could be compared per segment.

    The drafting study's fourth column was "what regressed even though the headline improved".
    There is no mechanism for it in this tree — ``held_out``, ``holdout``, ``backtest`` and
    ``shadow_run`` are zero hits repo-wide, verified against a working control probe — and on a
    definition that declares no dimensions there would be nothing to break the headline down by
    even if there were. Saying that plainly is the honest column; a green tick here would be a
    guard that passes because it never looked.
    """
    dims = tuple(getattr(metric, "dimensions", ()) or ())
    if not dims:
        return Claim(NOT_APPLICABLE,
                     "This definition declares no dimensions, so there is no segment to "
                     "compare and no per-segment regression to report.",
                     detail={"dimensions": []})
    return Claim(NOT_APPLICABLE,
                 f"{len(dims)} dimension(s) are declared, but no per-segment comparison is "
                 "computed yet — this report states the headline only.",
                 detail={"dimensions": list(dims)})


def population_of(db: Any, tables: Iterable[str], *, taken_at: str = "") -> Population:
    """How reproducible this read is, as a typed verdict.

    Never returns a bare nullable token. `db.snapshot.data_version` is fail-open to ``None`` and
    on BigQuery it is ALWAYS None (`snapshot._quote` double-quotes identifiers that BigQuery
    parses as string literals), so a report that stamped it raw would carry a permanently empty
    field that reads as "nothing moved".
    """
    stamp = taken_at or _now()
    names = tuple(str(t) for t in (tables or ()) if str(t).strip())
    try:
        from aughor.db.snapshot import as_of_supported, data_version
    except Exception as exc:                                   # pragma: no cover - import guard
        return Population(UNPINNABLE, reason=f"the snapshot seam is unavailable: {exc}",
                          tables=names, taken_at=stamp)

    token = ""
    try:
        if names:
            token = str(data_version(db, names) or "")
    except Exception:
        token = ""

    try:
        pinnable = bool(as_of_supported(db))
    except Exception:
        pinnable = False

    if pinnable and token:
        return Population(PINNED, token=token, tables=names, taken_at=stamp)
    if token:
        return Population(FINGERPRINTED, token=token, tables=names, taken_at=stamp)
    if not names:
        return Population(UNPINNABLE,
                          reason="the definition names no table, so there is no population to "
                                 "identify",
                          tables=names, taken_at=stamp)
    dialect = str(getattr(db, "dialect", "") or "unknown")
    return Population(
        UNPINNABLE,
        reason=(f"this connection ({dialect}) offers no version this read can be pinned to, and "
                "no fingerprint could be taken — the numbers above are one read of a table that "
                "may move"),
        tables=names, taken_at=stamp)


def build_report(metric: Any, db: Any = None, *,
                 connection_id: str = "",
                 audit_events: Sequence[Mapping[str, Any]] = (),
                 table_cols: Optional[Mapping[str, Sequence[str]]] = None,
                 taken_at: str = "") -> DefinitionReport:
    """Assemble the screen for one metric on one connection.

    ``metric`` must already be resolved FOR ``connection_id`` by the caller — this function does
    not look it up, because the lookup is where the live defect is: `get_metric` falls back to
    the global definition when a connection has none of its own, so a caller that does not then
    check ``metric.connection`` will report on a formula belonging to someone else.
    """
    stamp = taken_at or _now()
    tables = tuple(getattr(metric, "tables", ()) or ())
    return DefinitionReport(
        metric=str(getattr(metric, "name", "") or ""),
        connection_id=connection_id or str(getattr(metric, "connection", "") or ""),
        status=str(getattr(metric, "status", "") or ""),
        version=int(getattr(metric, "version", 0) or 0),
        predecessor=predecessor_claim(metric, audit_events),
        execution=execution_claim(metric, db),
        declaration=declaration_claim(metric, table_cols),
        segments=segments_claim(metric),
        population=population_of(db, tables, taken_at=stamp),
        taken_at=stamp,
    )
