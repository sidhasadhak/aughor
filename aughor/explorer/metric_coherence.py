"""Named-metric ↔ SQL coherence — the metric-naming/drift/relabel layer of the explorer's
pre-emission trust gate, extracted verbatim from explorer/agent.py (a 4k-line god-file) so it's a
cohesive, independently-testable module. Behavior is unchanged.

The bug this guards: the coder aliased `SUM(order_value)/COUNT(DISTINCT order_id) AS aov`
(correctly — that IS AOV), but the narrator wrote it up as "ROAS at 6.23"; that one wrong word
made the Briefing claim ROAS and the drill-down chase a revenue÷spend ratio with no clean grain.
The signal is the query's OWN label disagreeing with the claim. The metric vocabulary comes from
the per-industry KB (data/kb/industry/*.json) matched to the connection's profile, plus
org-registered metrics — so airline/manufacturing/SaaS are covered by their JSON, and a new metric
is a KB/registry entry, not a code change.

Public surface (the explorer gate + emission sites call these — kept public so the cross-module
import stays off the private-import ratchet): `mislabeled_named_metric`, `drifted_registered_metric`,
`relabel_mislabeled_finding`, `metric_vocab_for`. Everything else is module-private.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

_ALIAS_RE = re.compile(r"\bAS\s+\"?([A-Za-z_][A-Za-z0-9_]*)\"?", re.IGNORECASE)


def _kbnorm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _metric_of_sql_alias(sql: str, vocab: dict):
    """The canonical metric a query LABELS its result as — the label its top-level column alias
    resolves to in ``vocab`` ({token: (label, formula)}) — or None. Falls back to a regex scan of
    ``AS <ident>`` if the SQL won't parse."""
    cands: list = []
    try:
        import sqlglot as _sg
        from sqlglot import exp as _sgx
        tree = _sg.parse_one(sql, read="duckdb")
        for e in (getattr(tree, "expressions", None) or []):
            a = e.alias if isinstance(e, _sgx.Alias) else getattr(e, "alias", "")
            if a:
                cands.append(a)
    except Exception:
        cands = [m.group(1) for m in _ALIAS_RE.finditer(sql)]
    for a in cands:
        hit = vocab.get(_kbnorm(a))
        if hit:
            return hit[0]   # the canonical label
    return None


def _asserted_metrics_in_text(text: str, vocab: dict) -> set:
    """Canonical labels of vocab metrics ASSERTED in the prose — a name/alias appearing in a clause
    that ALSO carries a number ("ROAS at 6.23"), so a passing mention ('ROAS is worth checking')
    doesn't count. Single-word tokens match a clause word; longer tokens match the clause's
    normalized form (so 'return on ad spend' is caught)."""
    out: set = set()
    for clause in re.split(r"[.;\n]", (text or "").lower()):
        if not re.search(r"\d", clause):
            continue
        words = set(re.split(r"[^a-z0-9]+", clause))
        cnorm = _kbnorm(clause)
        for token, (label, _formula) in vocab.items():
            if token in words or (len(token) >= 6 and token in cnorm):
                out.add(label)
    return out


def mislabeled_named_metric(finding_text: str, sql: str, vocab: dict) -> str | None:
    """Reason when the query's result is aliased as one metric but the finding asserts a DIFFERENT
    one — a metric mislabel (AOV computed, "ROAS" claimed). High-precision: both must be recognized
    metrics from the industry KB / registry, and the claim must be asserted with a value."""
    if not finding_text or not sql or not vocab:
        return None
    sql_metric = _metric_of_sql_alias(sql, vocab)
    if not sql_metric:
        return None
    claimed = _asserted_metrics_in_text(finding_text, vocab)
    if claimed and sql_metric not in claimed:
        other = sorted(claimed)[0]
        return (f"metric mislabel: the query computes {sql_metric} (its result is aliased as such) "
                f"but the finding asserts {other}. Relabel the finding to {sql_metric}, or fix the "
                "query to actually compute the claimed metric.")
    return None


def _alias_stripped_norm(sql: str) -> str:
    """Normalized SQL with table qualifiers removed from columns, so a governed formula
    signature `SUM(total_amount)` matches an alias-prefixed query `SUM(o.total_amount)` —
    the alias-insensitivity check_metric_enforcement lacks (a correct prefixed query reads
    as 'drift' to its raw substring match). Fail-open to the plain normalization."""
    try:
        import sqlglot as _sg
        from sqlglot import exp as _sgx
        tree = _sg.parse_one(sql, read="duckdb")
        for c in tree.find_all(_sgx.Column):
            c.set("table", None)
        return _kbnorm(tree.sql(dialect="duckdb"))
    except Exception:
        return _kbnorm(sql)


def _wrong_usage_idents(metric) -> list[str]:
    """Column/table identifiers (snake_case) a metric's `wrong_usage_examples` warn against —
    the positive drift signal (`line_total` for order-grain revenue). Underscore-bearing only,
    so SQL keywords ('from', 'select') can't masquerade as a wrong column."""
    out: list[str] = []
    for ex in (getattr(metric, "wrong_usage_examples", []) or []):
        for ident in re.findall(r"[a-z]+_[a-z0-9_]+", ex.lower()):
            if ident not in out:
                out.append(ident)
    return out


def _asserted_registered(finding_text: str, metrics: list) -> list:
    """Registered metrics whose name/label the prose ASSERTS with a value (a number in the
    same clause) — a passing mention ('revenue is worth watching') doesn't count. Inlined
    targeting (not enforcement._targets) to keep the public-import boundary clean."""
    clauses = [c for c in re.split(r"[.;\n]", (finding_text or "").lower()) if re.search(r"\d", c)]
    if not clauses:
        return []
    out: list = []
    for m in metrics:
        name = (getattr(m, "name", "") or "").lower()
        label = (getattr(m, "label", "") or "").lower()
        words = [w for w in re.findall(r"[a-z]+", label) if len(w) >= 4]
        for c in clauses:
            cw = set(re.split(r"[^a-z0-9]+", c))
            if (name and name in cw) or (label and label in c) or (words and all(w in c for w in words)):
                out.append(m)
                break
    return out


def drifted_registered_metric(finding_text: str, sql: str) -> str | None:
    """The deeper coherence layer under the alias↔claim signal: a finding that ASSERTS a
    REGISTERED metric whose SQL structurally DRIFTS from that metric's governed formula —
    caught even with no revealing result alias (the alias guard needs one). High-precision:
    only registered metrics with a governed formula; the governed signature is checked
    alias-insensitively (so a correct prefixed query is never flagged); and a hard reject
    fires ONLY when a wrong-usage COLUMN the metric warns against is actually present (so a
    merely differently-written correct query is never dropped). Returns a reason or None."""
    if not finding_text or not sql:
        return None
    try:
        from aughor.semantic.metrics import list_metrics
        metrics = [m for m in list_metrics() if (getattr(m, "sql", "") or "").strip()]
    except Exception as _e:
        logger.debug("formula-drift: registry unavailable: %s", _e)
        return None
    asserted = _asserted_registered(finding_text, metrics)
    if not asserted:
        return None
    s = _alias_stripped_norm(sql)
    for m in asserted:
        formula = _kbnorm(getattr(m, "sql", ""))
        if not formula or formula in s:
            continue                       # governed formula present (alias-insensitive) → no drift
        # Governed formula ABSENT — corroborate with a wrong-usage column actually in the SQL.
        for ident in _wrong_usage_idents(m):
            n = _kbnorm(ident)
            if len(n) >= 6 and n not in formula and n in s:
                lbl = getattr(m, "label", "") or getattr(m, "name", "")
                return (f"metric formula drift: the finding asserts {lbl} but the query uses a "
                        f"non-governed form (references '{ident}'; governed: {getattr(m, 'sql', '')}). "
                        "Recompute with the governed formula or relabel to what the SQL computes.")
    return None


def _row_floats(rows) -> list:
    """Every numeric cell value in the result, for grounding an asserted number. Type-checked
    (no try/except) so a non-numeric cell is simply skipped — bool excluded (it's not a measure)."""
    out: list = []
    for r in rows or []:
        for v in (r.values() if isinstance(r, dict) else r):
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                out.append(float(v))
            elif isinstance(v, str) and re.fullmatch(r"\s*-?\d+(?:\.\d+)?\s*", v):
                out.append(float(v.strip()))
    return out


def _wrong_metric_value_grounded(finding_text: str, vocab: dict, wrong_labels: set, rows) -> bool:
    """STRICT grounding for relabel: every number in a clause that asserts a WRONG-labelled metric
    must actually appear in the result rows (1% tolerant, percent↔fraction-aware). Stricter than
    the lenient emission gate (which skips small numbers) — so relabel can NEVER keep a fabricated
    value like the 'ROAS 6.23' a query returning AOV ~69 never produced. No cells / no asserted
    number → not grounded (don't rescue)."""
    cells = _row_floats(rows)
    if not cells:
        return False
    wrong_tokens = {tok for tok, (label, _f) in vocab.items() if label in wrong_labels}
    nums: list = []
    for clause in re.split(r"[.;\n]", (finding_text or "").lower()):
        words = set(re.split(r"[^a-z0-9]+", clause))
        cnorm = _kbnorm(clause)
        if any(t in words or (len(t) >= 6 and t in cnorm) for t in wrong_tokens):
            nums += [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", clause.replace(",", ""))]
    if not nums:
        return False

    def grounded(n: float) -> bool:
        for c in cells:
            if abs(n - c) <= max(0.05, abs(c) * 0.01):
                return True
            if abs(n - c * 100.0) <= max(0.05, abs(c * 100.0) * 0.01):   # cell is a fraction, prose a percent
                return True
        return False

    return all(grounded(n) for n in nums)


def relabel_mislabeled_finding(finding_text: str, sql: str, vocab: dict, rows=None) -> str | None:
    """Relabel-and-keep: when a finding is mislabeled (the query computes metric A but the prose
    asserts a DIFFERENT metric B with a value), rewrite B's name to A's canonical label and KEEP
    the finding instead of dropping it — the SIGNAL is real, only the label was wrong (the missimi
    'email CRM AOV $69.15' that a bad LLM draw called 'ROAS').

    Safe by a STRICT internal grounding gate: it relabels ONLY when the wrong metric's asserted
    value(s) are present in the result rows — so a mislabel whose number was ALSO fabricated
    ('ROAS 6.23' over rows that are ~69) is NOT rescued and falls through to the normal reject (the
    emission gate's grounding is too lenient on small numbers to be relied on here). Only single-word
    recognized metric tokens that appear verbatim (ROAS/AOV/CAC…) are rewritten — a multi-word phrase
    can't be located reliably. Returns the relabeled text, or None when there's nothing to safely relabel."""
    if not finding_text or not sql or not vocab:
        return None
    sql_metric = _metric_of_sql_alias(sql, vocab)
    if not sql_metric:
        return None
    claimed = _asserted_metrics_in_text(finding_text, vocab)
    wrong_labels = {c for c in claimed if c != sql_metric}
    if not wrong_labels:
        return None
    if not _wrong_metric_value_grounded(finding_text, vocab, wrong_labels, rows):
        return None   # the asserted value isn't this query's output → don't keep a wrong number
    # surface tokens (single alnum words like 'roas') that map to a wrong label — longest first.
    wrong_tokens = sorted(
        {tok for tok, (label, _f) in vocab.items() if label in wrong_labels and tok.isalnum()},
        key=len, reverse=True)
    new_text, replaced = finding_text, False
    for tok in wrong_tokens:
        pat = re.compile(rf"\b{re.escape(tok)}\b", re.I)
        if pat.search(new_text):
            new_text = pat.sub(sql_metric, new_text)
            replaced = True
    return new_text if replaced else None


@lru_cache(maxsize=64)
def _industry_for_conn(conn_id: str) -> str:
    """The connection's declared/inferred industry, for industry-scoped metric vocabulary."""
    if not conn_id:
        return ""
    try:
        from aughor.profile import store as _pstore
        bp = _pstore.load(conn_id)
        return (getattr(bp, "industry", "") or "") if bp else ""
    except Exception:
        return ""


def metric_vocab_for(conn, industry: str = "") -> dict:
    """{normalized_token: (label, formula)} for the coherence check — the per-industry curated KB
    matched to this connection's profile, plus org-registered metric names. Fail-open to {}."""
    try:
        ind = (industry or "").strip()
        if not ind and conn is not None:
            ind = _industry_for_conn(getattr(conn, "_connection_id", "") or "")
        from aughor.profile.metric_kb import metric_vocabulary
        vocab = {t: (label, formula) for (t, label, formula) in metric_vocabulary(ind)}
        try:    # org-registered metrics (governed) extend the vocabulary by name + label
            from aughor.semantic.metrics import list_metrics
            for m in list_metrics():
                label = getattr(m, "label", "") or getattr(m, "name", "")
                for tok in (getattr(m, "name", ""), label):
                    t = _kbnorm(tok)
                    if t and t not in vocab:
                        vocab[t] = (label, getattr(m, "sql", "") or "")
        except Exception as _e:
            logger.debug("metric vocab: registry metrics unavailable: %s", _e)
        return vocab
    except Exception as _e:
        logger.debug("metric vocab build failed: %s", _e)
        return {}
