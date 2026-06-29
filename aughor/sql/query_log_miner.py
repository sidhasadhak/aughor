"""Query-log mining — learn how a database is ACTUALLY queried, from real query history.

Motivation: Shkapenyuk, Srivastava, Johnson & Ghane, *Automatic Metadata Extraction for Text-to-SQL*
(AT&T CDO; the system that repeatedly held #1 on the BIRD leaderboard). Their thesis — matching
Aughor's own grounded direction — is that the hard part of NL2SQL is understanding the database, and
a large fraction of what you need is **undocumented in the schema but recoverable from the query
log**. They measured ~25% MORE equality join constraints in the query log than in the declared FKs,
plus filter predicates and named business formulas that exist only in how analysts actually query.

This module mines a list of historical SQL strings into DETERMINISTIC, reusable facts:
  * join edges     — ``a.col = b.col`` equalities across tables, ranked by how often they appear,
  * filter values  — common ``col = 'literal'`` / ``col IN (...)`` predicates (the real value domain),
  * named formulas — recurring ``<expression> AS <name>`` computations (the real business logic),
  * column usage   — which columns are actually referenced (a schema-linking recall signal).

It is pure and backend-agnostic (in: ``list[str]``; out: :class:`QueryLogFacts`) — the SOURCE of the
queries is pluggable: Aughor's own logged queries now (:func:`collect_logged_sql`), the warehouse
``QUERY_HISTORY`` once credentials land. The facts are parsed from real SQL, not a model opinion —
the grounding-beats-machinery lever that holds up on strong models — so the rendered block can be
fed straight into the schema context the way value-verified join hints and profiles already are.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import sqlglot
from sqlglot import exp


def _alias_to_table(tree: exp.Expression) -> dict[str, str]:
    """Map every table alias and bare name (lowercased) to its real table name."""
    m: dict[str, str] = {}
    for t in tree.find_all(exp.Table):
        m[t.name.lower()] = t.name
        if t.alias:
            m[t.alias.lower()] = t.name
    return m


def _is_computation(e: exp.Expression) -> bool:
    """True when a SELECT projection is a real computed formula (function / arithmetic / CASE /
    window), not a bare column, literal, or ``*`` — i.e. worth recording as business logic."""
    if isinstance(e, (exp.Column, exp.Literal, exp.Star, exp.Null)):
        return False
    if isinstance(e, (exp.Func, exp.Case, exp.Window)):
        return True
    if isinstance(e, exp.Paren):
        return _is_computation(e.this)
    # arithmetic (Add/Sub/Mul/Div are exp.Binary) or anything wrapping a function call
    return isinstance(e, exp.Binary) or e.find(exp.Func) is not None


@dataclass
class QueryLogFacts:
    """Deterministic facts mined from a query log. Counters are keyed for stable, ranked rendering."""
    n_queries: int = 0
    n_parsed: int = 0
    join_edges: Counter = field(default_factory=Counter)        # "a.c1 = b.c2" (sorted) -> count
    filter_values: dict = field(default_factory=dict)           # "t.col" -> Counter(literal -> count)
    named_formulas: Counter = field(default_factory=Counter)    # (name, expr_sql) -> count
    column_usage: Counter = field(default_factory=Counter)      # "t.col" -> count

    def render_for_schema_context(
        self, *, min_support: int = 1, max_joins: int = 20, max_filter_cols: int = 12,
        per_col: int = 8, max_formulas: int = 15,
    ) -> str:
        """Render the highest-signal facts as a comment block for the LLM schema context.

        ``min_support`` keeps only facts seen at least N times (drops one-off noise — the paper's
        value is in *recurring* patterns). Returns "" when nothing clears the bar."""
        if self.n_parsed == 0:
            return ""
        joins = [(e, n) for e, n in self.join_edges.most_common() if n >= min_support][:max_joins]
        formulas = [(k, n) for k, n in self.named_formulas.most_common() if n >= min_support][:max_formulas]
        filt_cols = sorted(
            ((qc, c) for qc, c in self.filter_values.items() if sum(c.values()) >= min_support),
            key=lambda kv: sum(kv[1].values()), reverse=True,
        )[:max_filter_cols]
        if not (joins or formulas or filt_cols):
            return ""

        lines = [f"-- LEARNED FROM QUERY HISTORY ({self.n_parsed} queries analyzed):"]
        if joins:
            lines.append("-- Observed join paths (used in practice; some may not be declared FKs):")
            lines += [f"--   {e}  (seen {n}×)" for e, n in joins]
        if filt_cols:
            lines.append("-- Observed filter values (the real value domain in use):")
            for qc, counter in filt_cols:
                vals = ", ".join(f"'{v}'" for v, _ in counter.most_common(per_col))
                lines.append(f"--   {qc} IN ({vals})")
        if formulas:
            lines.append("-- Observed business formulas (recurring computed expressions):")
            lines += [f"--   {name} := {expr}  (seen {n}×)" for (name, expr), n in formulas]
        return "\n".join(lines)


def mine_query_log(sqls: list[str], dialect: str = "duckdb") -> QueryLogFacts:
    """Parse each SQL string and accumulate deterministic facts. Never raises; unparseable queries
    are skipped (counted only in ``n_queries``)."""
    facts = QueryLogFacts(n_queries=len(sqls))
    for sql in sqls:
        if not sql or not sql.strip():
            continue
        tree = None
        try:
            tree = sqlglot.parse_one(sql, read=dialect)
        except Exception:
            try:
                tree = sqlglot.parse_one(sql)          # dialect-agnostic retry
            except Exception:
                tree = None
        if tree is None:
            continue
        facts.n_parsed += 1

        a2t = _alias_to_table(tree)
        all_tables = {t.name for t in tree.find_all(exp.Table)}
        single = next(iter(all_tables)) if len(all_tables) == 1 else None

        def _qual(col: exp.Column) -> Optional[str]:
            if col.table:
                t = a2t.get(col.table.lower())
                return f"{t}.{col.name}" if t else None
            return f"{single}.{col.name}" if single else None

        def _literal(node: exp.Expression) -> Optional[str]:
            return (node.this if node.is_string else node.name) if isinstance(node, exp.Literal) else None

        for eq in tree.find_all(exp.EQ):
            left, right = eq.left, eq.right
            if isinstance(left, exp.Column) and isinstance(right, exp.Column):
                ql, qr = _qual(left), _qual(right)
                if ql and qr and ql.split(".")[0].lower() != qr.split(".")[0].lower():
                    facts.join_edges[" = ".join(sorted([ql, qr]))] += 1
            else:                                      # column = literal filter
                col = left if isinstance(left, exp.Column) else (right if isinstance(right, exp.Column) else None)
                lit = _literal(left) or _literal(right)
                if col is not None and lit is not None:
                    qc = _qual(col)
                    if qc:
                        facts.filter_values.setdefault(qc, Counter())[str(lit)] += 1

        for inn in tree.find_all(exp.In):
            if isinstance(inn.this, exp.Column):
                qc = _qual(inn.this)
                if qc:
                    for e in inn.expressions:
                        lit = _literal(e)
                        if lit is not None:
                            facts.filter_values.setdefault(qc, Counter())[str(lit)] += 1

        for sel in tree.find_all(exp.Select):
            for proj in sel.expressions:
                if isinstance(proj, exp.Alias) and _is_computation(proj.this):
                    facts.named_formulas[(proj.alias, proj.this.sql())] += 1

        for c in tree.find_all(exp.Column):
            qc = _qual(c)
            if qc:
                facts.column_usage[qc] += 1

    return facts


def collect_logged_sql(connection_id: str = "", limit: int = 5000) -> list[str]:
    """Pull historical SQL strings Aughor has already logged for a connection (best-effort).

    Source = the SQL-examples vector store populated by ``prior_analyses.index_sql_examples`` (every
    clean, non-empty query Aughor has run). Returns [] when the store is unavailable — the schema
    context still builds without it. This is the runnable-now source; a warehouse ``QUERY_HISTORY``
    reader can feed the same :func:`mine_query_log` once credentials land."""
    try:
        from aughor.semantic.vector_store import scroll_payloads
        from aughor.tools.prior_analyses import SQL_EXAMPLES_COLLECTION
        payloads = scroll_payloads(SQL_EXAMPLES_COLLECTION, limit=limit)
    except Exception as e:
        from aughor.kernel.errors import tolerate
        tolerate(e, "query-log collection is best-effort; schema context builds without it",
                 counter="query_log.collect", conn_id=connection_id or None)
        return []
    out: list[str] = []
    for p in payloads:
        if connection_id and p.get("connection_id") not in ("", connection_id):
            continue
        sql = p.get("sql")
        if sql:
            out.append(sql)
    return out


def build_query_log_annotation(connection_id: str = "", dialect: str = "duckdb",
                               *, min_support: int = 1) -> str:
    """Convenience: collect this connection's logged SQL, mine it, and render the schema-context
    block in one call. Returns "" when there is no usable history."""
    sqls = collect_logged_sql(connection_id)
    if not sqls:
        return ""
    return mine_query_log(sqls, dialect=dialect).render_for_schema_context(min_support=min_support)
