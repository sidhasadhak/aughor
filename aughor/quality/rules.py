"""Wave Q1 — the declarative rule catalog.

**Criticality is data, not code.** The same check `warn`s on one table and `error`s on
another, because whether a null in `customer_email` is a nuisance or a stop-the-line defect
is a business fact about that table, not a property of the not-null check. A catalog that
hard-coded severity per check kind would force a fork of the check to express a different
opinion about it.

**The fingerprint excludes metadata, and that is load-bearing.** DQX's trick, and the
reason it matters here is concrete: a rule's stored results are keyed by the fingerprint of
the rule that produced them (Q3). If editing a rule's `note` changed its fingerprint, every
historical result would detach from its rule, and the only way to keep history would be to
never annotate a rule. So the hash covers what the rule *computes* — kind, column, args,
filter — and never what it *says about itself*.

**Compiled through the path that already exists.** The Q pre-check confirmed
``tree.sql(dialect=…)`` is how this codebase emits per-dialect SQL — `monitors/window.py`,
`sql/aliases.py` and `sql/cost.py` all do it — so checks compile that way rather than
through a second SQL-emitting convention. Assuming this rather than checking it is what
Wave G's four wrong premises cost.

Every check is DETERMINISTIC. A quality plane whose verdicts a model authored cannot be the
thing that gates a publish, so no rule here takes a model call, and LLM involvement is
confined to *proposing* candidate rules (Q2), which a human accepts.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

#: What a failure means. Data, not code — see the module docstring.
CRITICALITIES: tuple[str, ...] = ("warn", "error")

#: The BI-trust check kinds. Deliberately a closed set: an unknown kind must fail loudly at
#: catalog-load rather than silently never running, which is a check that reports healthy
#: because it never executed.
CHECK_KINDS: tuple[str, ...] = (
    "not_null",
    "unique",
    "foreign_key",
    "in_list",
    "range",
    "freshness",
    "row_count_drift",
    "accepted_values_drift",
)

#: Fields that describe a rule to a HUMAN and never change what it computes. Excluded from
#: the fingerprint so annotating a rule does not orphan its history.
_METADATA_FIELDS: frozenset[str] = frozenset({"note", "owner", "title", "tags", "criticality"})


class RuleError(ValueError):
    """A malformed rule. Raised at load rather than skipped: a skipped check reports
    healthy because it never ran, which is the worst possible quality signal."""


@dataclass
class Rule:
    """One declarative check on one table."""

    name: str
    table: str
    kind: str
    column: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    filter: str = ""                      # optional WHERE applied before checking
    criticality: str = "warn"
    for_each_column: tuple[str, ...] = ()  # expand into one rule per column
    note: str = ""
    owner: str = ""

    def validate(self) -> None:
        if not self.name.strip():
            raise RuleError("a rule needs a name")
        if not self.table.strip():
            raise RuleError(f"rule {self.name!r} needs a table")
        if self.kind not in CHECK_KINDS:
            raise RuleError(
                f"rule {self.name!r} has unknown kind {self.kind!r} — known: "
                f"{list(CHECK_KINDS)}")
        if self.criticality not in CRITICALITIES:
            raise RuleError(
                f"rule {self.name!r} has unknown criticality {self.criticality!r} — "
                f"known: {list(CRITICALITIES)}")
        needs_column = self.kind in ("not_null", "in_list", "range", "freshness")
        if needs_column and not (self.column or self.for_each_column):
            raise RuleError(f"rule {self.name!r} ({self.kind}) needs a column")
        if self.kind == "in_list" and not self.args.get("values"):
            raise RuleError(f"rule {self.name!r} (in_list) needs args.values")
        if self.kind == "range":
            if self.args.get("min") is None and self.args.get("max") is None:
                raise RuleError(f"rule {self.name!r} (range) needs args.min or args.max")
        if self.kind == "freshness" and not self.args.get("max_age_hours"):
            raise RuleError(f"rule {self.name!r} (freshness) needs args.max_age_hours")
        if self.kind == "foreign_key" and not (self.args.get("references")
                                               and self.args.get("references_column")):
            raise RuleError(
                f"rule {self.name!r} (foreign_key) needs args.references and "
                f"args.references_column")

    def semantic_payload(self) -> dict:
        """Exactly what this rule COMPUTES — the fingerprint's input.

        Metadata is excluded (see the module docstring). ``criticality`` is excluded too,
        which is the less obvious call: changing warn→error changes what a failure MEANS
        but not what was measured, and re-fingerprinting on it would detach the history
        that makes the escalation reviewable in the first place.
        """
        return {
            "table": self.table.split(".")[-1].lower(),
            "kind": self.kind,
            "column": self.column.lower(),
            "args": self.args,
            "filter": " ".join(self.filter.split()).lower(),
            "for_each_column": sorted(c.lower() for c in self.for_each_column),
        }

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(self.semantic_payload(), sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def expand(self) -> list["Rule"]:
        """``for_each_column`` → one rule per column. A rule with none returns itself."""
        self.validate()
        if not self.for_each_column:
            return [self]
        out = []
        for col in self.for_each_column:
            out.append(Rule(name=f"{self.name}:{col}", table=self.table, kind=self.kind,
                            column=col, args=dict(self.args), filter=self.filter,
                            criticality=self.criticality, note=self.note,
                            owner=self.owner))
        return out

    def to_dict(self) -> dict:
        return {"name": self.name, "table": self.table, "kind": self.kind,
                "column": self.column, "args": self.args, "filter": self.filter,
                "criticality": self.criticality,
                "for_each_column": list(self.for_each_column),
                "note": self.note, "owner": self.owner,
                "fingerprint": self.fingerprint}


@dataclass
class RuleSet:
    """A connection's rules, with a fingerprint over the set."""

    connection_id: str
    rules: list[Rule] = field(default_factory=list)

    def validate(self) -> None:
        seen: set[str] = set()
        for r in self.rules:
            r.validate()
            if r.name in seen:
                raise RuleError(f"duplicate rule name {r.name!r} in the ruleset")
            seen.add(r.name)

    @property
    def fingerprint(self) -> str:
        """Order-independent: reordering a YAML file is not a change to what runs."""
        raw = "|".join(sorted(r.fingerprint for r in self.rules))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def expanded(self) -> list[Rule]:
        out: list[Rule] = []
        for r in self.rules:
            out.extend(r.expand())
        return out

    def to_dict(self) -> dict:
        return {"connection_id": self.connection_id,
                "fingerprint": self.fingerprint,
                "rules": [r.to_dict() for r in self.rules]}


# ── compilation ─────────────────────────────────────────────────────────────────────

def _q(value: Any) -> str:
    """A SQL literal. Strings are single-quote-escaped; everything else is rendered bare.

    Rules come from a governed YAML file rather than a request, but a value dictionary
    mined from data can reach ``in_list``, so quoting is done rather than assumed safe.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def compile_rule(rule: Rule, dialect: str = "duckdb") -> str:
    """The SQL that COUNTS violations of one rule. Deterministic; no model call.

    Returns a query yielding a single ``violations`` column. Counting rather than
    selecting rows is the whole design: a check that returned offending rows would put
    warehouse data into a result store that has no clearance model, and Wave G spent a
    whole wave on why that matters.
    """
    rule.validate()
    if rule.for_each_column:
        raise RuleError(
            f"rule {rule.name!r} must be expanded before compiling — call expand()")

    table = rule.table
    col = rule.column
    where: list[str] = []
    if rule.filter.strip():
        where.append(f"({rule.filter.strip()})")

    if rule.kind == "not_null":
        where.append(f"{col} IS NULL")
    elif rule.kind == "in_list":
        values = ", ".join(_q(v) for v in rule.args["values"])
        where.append(f"{col} NOT IN ({values})")
    elif rule.kind == "range":
        lo, hi = rule.args.get("min"), rule.args.get("max")
        bounds = []
        if lo is not None:
            bounds.append(f"{col} < {_q(lo)}")
        if hi is not None:
            bounds.append(f"{col} > {_q(hi)}")
        where.append("(" + " OR ".join(bounds) + ")")
    elif rule.kind == "freshness":
        hours = int(rule.args["max_age_hours"])
        # Emitted as a generic interval comparison and transpiled; the pre-check confirmed
        # `.sql(dialect=…)` is this codebase's emit path.
        sql = (f"SELECT COUNT(*) AS violations FROM {table} "
               f"WHERE {col} < CURRENT_TIMESTAMP - INTERVAL '{hours}' HOUR")
        return _transpile(sql, dialect)
    elif rule.kind == "unique":
        keys = rule.args.get("columns") or ([col] if col else [])
        if not keys:
            raise RuleError(f"rule {rule.name!r} (unique) needs a column or args.columns")
        key_list = ", ".join(keys)
        filt = f"WHERE {' AND '.join(where)} " if where else ""
        sql = (f"SELECT COUNT(*) AS violations FROM (SELECT {key_list} FROM {table} "
               f"{filt}GROUP BY {key_list} HAVING COUNT(*) > 1) d")
        return _transpile(sql, dialect)
    elif rule.kind == "foreign_key":
        ref, ref_col = rule.args["references"], rule.args["references_column"]
        filt = f"AND {' AND '.join(where)} " if where else ""
        sql = (f"SELECT COUNT(*) AS violations FROM {table} t "
               f"LEFT JOIN {ref} r ON t.{col} = r.{ref_col} "
               f"WHERE t.{col} IS NOT NULL AND r.{ref_col} IS NULL {filt}".strip())
        return _transpile(sql, dialect)
    elif rule.kind in ("row_count_drift", "accepted_values_drift"):
        # Drift needs a baseline, which lives in the results store (Q3) — the rule
        # compiles to the OBSERVATION, and the comparison happens against history.
        if rule.kind == "row_count_drift":
            sql = f"SELECT COUNT(*) AS violations FROM {table}"
        else:
            sql = (f"SELECT COUNT(DISTINCT {col}) AS violations FROM {table}")
        return _transpile(sql, dialect)
    else:                                              # pragma: no cover — closed set
        raise RuleError(f"no compiler for kind {rule.kind!r}")

    sql = f"SELECT COUNT(*) AS violations FROM {table} WHERE {' AND '.join(where)}"
    return _transpile(sql, dialect)


def _transpile(sql: str, dialect: str) -> str:
    """Emit for the target dialect through the path this codebase already uses.

    A transpile failure returns the generic SQL rather than raising: the query is
    ANSI-shaped and most engines accept it, and refusing to check a table because a
    transpiler had an opinion would turn a cosmetic problem into a coverage gap.
    """
    try:
        import sqlglot

        return sqlglot.parse_one(sql, read="duckdb").sql(dialect=dialect or "duckdb")
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "check SQL falls back to generic dialect rather than not running",
                 counter="quality.rule_transpile")
        return sql


def rule_from_dict(raw: dict) -> Rule:
    """Build and validate one rule from stored YAML."""
    rule = Rule(
        name=str(raw.get("name") or ""),
        table=str(raw.get("table") or ""),
        kind=str(raw.get("kind") or ""),
        column=str(raw.get("column") or ""),
        args=dict(raw.get("args") or {}),
        filter=str(raw.get("filter") or ""),
        criticality=str(raw.get("criticality") or "warn"),
        for_each_column=tuple(raw.get("for_each_column") or ()),
        note=str(raw.get("note") or ""),
        owner=str(raw.get("owner") or ""))
    rule.validate()
    return rule


def ruleset_from_dict(connection_id: str, raw: dict) -> RuleSet:
    rs = RuleSet(connection_id=connection_id,
                 rules=[rule_from_dict(r) for r in (raw.get("rules") or [])])
    rs.validate()
    return rs


def metadata_fields() -> frozenset[str]:
    """The fields excluded from the fingerprint — exposed so a test can pin the rule."""
    return _METADATA_FIELDS
