#!/usr/bin/env python3
"""quality_sweep.py — exhaustive Insight (/chat) + Deep Analysis (/investigate) sweep
across every connection, capturing the EXACT output (text, SQL, per-finding columns +
charts) and auto-flagging quality defects so the platform can grade itself.

Extends answer_sweep.py with:
  • a 10-15 question battery per connection (ranking / aggregate / average / breakdown
    / temporal / cross-sectional-diagnostic / change-diagnostic intents),
  • FINDING-LEVEL flags that catch the exact #25 bug class:
       DESYNC   — a card's title names a dimension that is NOT its chart's category
                  column ("says city but the chart shows country").
       CHARTPCT — a finding whose narrative cites $/absolute values but whose only
                  chartable numeric is a pct/share column (the web would plot the %).
       NOAVG    — a cross-sectional finding with no average / per-record lens.
  • report-level flags (SIGN / FRAME / CONF) carried over from answer_sweep,
  • resumable runs (skips cases already in the JSONL) + --conn / --mode / --limit so a
    run can be paced against usage limits and continued later,
  • a written markdown report (data/quality_sweep_report.md).

Usage:
  uv run python scripts/quality_sweep.py                 # full sweep (resumes)
  uv run python scripts/quality_sweep.py --conn c1c664b0 # one connection
  uv run python scripts/quality_sweep.py --mode investigate --limit 8
  uv run python scripts/quality_sweep.py --fresh         # ignore prior JSONL
"""
import argparse
import json
import re
import time
import uuid
import urllib.request
import urllib.error

# Reuse the explorer's generation-time guards as live-sweep detectors so the
# harness self-grades for the same classes (#4 — eval fixtures from real repros).
try:
    from aughor.explorer.verify import has_fabricated_dimension, mislabeled_per_grain
except Exception:  # pragma: no cover — harness still runs without the guards
    has_fabricated_dimension = lambda sql: False          # noqa: E731
    mislabeled_per_grain = lambda sql, txt="": False       # noqa: E731

BASE = "http://localhost:8000"
SESSION = "qsweep-" + uuid.uuid4().hex[:8]
OUT_JSONL = "data/quality_sweep.jsonl"
OUT_REPORT = "data/quality_sweep_report.md"

# ── Question batteries ────────────────────────────────────────────────────────
# (mode, question). mode: "ask" = Insight, "investigate" = Deep Analysis.
BATTERIES = {
    "c1c664b0": [  # beautycommerce — ecommerce: orders, attribution, marketing
        ("ask", "Top 10 products by revenue"),
        ("ask", "Show me total revenue by month"),
        ("ask", "What is the average order value?"),
        ("ask", "Revenue by marketing channel"),
        ("ask", "How many orders were placed in total?"),
        ("ask", "Top 10 customers by spend"),
        ("investigate", "Where are we losing money?"),
        ("investigate", "Why did revenue change recently?"),
        ("investigate", "Which marketing channel is underperforming?"),
        ("investigate", "Which products are weakest?"),
    ],
    "eed00c42": [  # tpch_sf1 — customer/orders/lineitem/nation/region/supplier/part
        ("ask", "Top 10 customers by revenue"),
        ("ask", "Total revenue by region"),
        ("ask", "What is the average order value?"),
        ("ask", "Revenue by nation"),
        ("ask", "Top 10 parts by revenue"),
        ("ask", "Order count by order priority"),
        ("investigate", "Where are we losing money?"),
        ("investigate", "Which region is weakest?"),
        ("investigate", "Which market segment underperforms on revenue?"),
    ],
    "f809a5c6": [  # tpcds — store_sales/item/customer/store
        ("ask", "Top selling items by sales"),
        ("ask", "Total sales by store"),
        ("ask", "What is the average sale amount?"),
        ("ask", "Sales by item category"),
        ("ask", "Top 10 customers by sales"),
        ("investigate", "Where are we losing money?"),
        ("investigate", "Which store is weakest?"),
        ("investigate", "Which item category underperforms?"),
    ],
    "9fbaa6f9": [  # clickbench — web analytics hits (no money metric — FRAME edge cases)
        ("ask", "What are the top 10 most visited pages?"),
        ("ask", "How many hits per day?"),
        ("ask", "Average hits per user"),
        ("ask", "Top traffic sources by hits"),
        ("ask", "Hits by region"),
        ("investigate", "Which traffic source is weakest?"),
        ("investigate", "Where is engagement lowest?"),
    ],
    "workspace": [  # federated bakehouse + ecommerce
        ("ask", "Show me total sales by franchise"),
        ("ask", "Top franchises by revenue"),
        ("ask", "What is the average sale per franchise?"),
        ("investigate", "Where are we losing money?"),
        ("investigate", "Which franchise is weakest?"),
    ],
}
CONN_LABEL = {
    "c1c664b0": "beautycommerce", "eed00c42": "tpch_sf1", "f809a5c6": "tpcds_sf1",
    "9fbaa6f9": "clickbench", "workspace": "bakehouse+ecommerce",
}

# ── SSE plumbing ──────────────────────────────────────────────────────────────
def sse_post(path, payload, timeout):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    events = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except Exception:
                    pass
    return events

# ── Heuristics ────────────────────────────────────────────────────────────────
_SHARE_RE = re.compile(r"(pct|percent|share|proportion|_of_total)", re.I)
_AVG_RE = re.compile(r"(avg|average|per_record|mean|_per_)", re.I)
_DATE_RE = re.compile(r"(date|month|year|week|day|_ts$|time|quarter)", re.I)
_MONEY_TXT = re.compile(r"\$\s?\d|\d+\s?(usd|dollars|eur|gbp)", re.I)
_DIM_STOP = {
    "by", "per", "across", "of", "the", "a", "an", "and", "or", "for", "to", "in",
    "on", "total", "net", "gross", "sum", "avg", "average", "count", "number",
    "share", "pct", "percent", "ratio", "rate", "value", "amount", "metric",
    "revenue", "sales", "profit", "margin", "cost", "spend", "orders", "order",
    "monthly", "weekly", "daily", "trend", "time", "change", "scan", "weakest",
    "lowest", "top", "bottom", "breakdown",
}


def _dim_tokens(s):
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower())
            if len(t) > 1 and t not in _DIM_STOP}


def has_neg(s):
    return bool(re.search(r"-\s*\$?\d", str(s or "")))


def is_money_metric(text):
    return bool(re.search(r"revenue|sales|profit|margin|cost|spend|gmv|income|dollar|\$", text or "", re.I))


def is_offtopic_metric(text):
    return bool(re.search(r"sentiment|review|rating|star|nps|satisfaction", text or "", re.I))


def finding_flags(phase_id, f):
    """Per-finding defect detection — the heart of the #25 self-check."""
    flags = []
    cols = f.get("columns") or []
    if not cols or f.get("error"):
        return flags
    title = f.get("title") or ""
    interp = f.get("interpretation") or ""
    cat = cols[0]  # category / dimension column the chart plots on the x/y label axis

    # DESYNC — title names a dimension absent from the charted category column.
    t_tok, c_tok = _dim_tokens(title), _dim_tokens(cat)
    if t_tok and c_tok and not (t_tok & c_tok):
        flags.append(f"DESYNC[{phase_id}]: title {title[:34]!r} vs chart cat col {cat!r}")

    # CHARTPCT — narrative cites $/absolute but the only chartable numeric is a share %.
    numeric = [c for i, c in enumerate(cols) if i > 0]
    share_cols = [c for c in numeric if _SHARE_RE.search(c)]
    nonshare_num = [c for c in numeric if not _SHARE_RE.search(c) and not _DATE_RE.search(c)]
    if share_cols and not nonshare_num and _MONEY_TXT.search(interp):
        flags.append(f"CHARTPCT[{phase_id}]: only share cols {share_cols} chartable but interp cites $")

    # NOAVG — a cross-sectional finding with no average / per-record lens.
    if phase_id == "cross_section" and not any(_AVG_RE.search(c) for c in cols):
        flags.append(f"NOAVG[{phase_id}]: no average column")

    # FABRICATED — the SQL groups by a constant literal (a stubbed-in dimension,
    # the 'Unknown' AS signup_source class).
    sql = f.get("sql") or ""
    if has_fabricated_dimension(sql):
        flags.append(f"FABRICATED[{phase_id}]: groups by a constant literal (fabricated dimension)")

    # AOV — a line-item AVG narrated as a per-order/per-customer metric.
    if mislabeled_per_grain(sql, f"{title} {interp}"):
        flags.append(f"AOV[{phase_id}]: line-item AVG labelled as a per-order metric")
    return flags


def analyze_deep(rec):
    flags = []
    ada = rec.get("ada_report") or {}
    wf = ada.get("attribution_waterfall") or []
    tcl = ada.get("total_change_label") or ""
    conf = (ada.get("confidence") or "").upper()
    headline = ada.get("headline") or ""
    summary = ada.get("executive_summary") or ""
    phases = ada.get("phases") or []

    for w in wf:
        pct = w.get("pct_of_total")
        amt = w.get("amount_label") or ""
        if pct is None:
            continue
        if (pct < 0) != has_neg(amt):
            flags.append(f"SIGN: cause {(w.get('cause') or '')[:26]!r} pct={pct} amt={amt!r}")
    if wf:
        net = sum((w.get("pct_of_total") or 0) for w in wf)
        if has_neg(tcl) and net > 5:
            flags.append(f"SIGN: total_change {tcl!r} negative but waterfall net=+{net:.0f}")
        if (not has_neg(tcl)) and re.search(r"\d", tcl) and net < -5:
            flags.append(f"SIGN: total_change {tcl!r} positive but waterfall net={net:.0f}")

    all_f = [f for p in phases for f in (p.get("findings") or [])]
    rows_seen = sum(1 for f in all_f if (f.get("columns") and f.get("rows")))
    errored = sum(1 for f in all_f if f.get("error"))
    if conf in ("HIGH", "MEDIUM") and rows_seen == 0:
        flags.append(f"CONF: {conf} but ZERO findings returned data (errors={errored})")

    q = rec.get("question", "")
    if re.search(r"losing money|profit|margin|revenue", q, re.I):
        target = (ada.get("metric") or "") + " " + headline + " " + summary
        if is_offtopic_metric(headline) or is_offtopic_metric(ada.get("metric") or ""):
            flags.append(f"FRAME: money question → off-topic metric (headline={headline[:50]!r})")
        elif not is_money_metric(target):
            flags.append(f"FRAME: money question but no money metric (headline={headline[:50]!r})")

    # finding-level sweep across every phase
    for p in phases:
        pid = p.get("phase_id") or ""
        for f in (p.get("findings") or []):
            flags.extend(finding_flags(pid, f))
    return flags


# ── Case runner ───────────────────────────────────────────────────────────────
def run_case(conn, label, mode, question):
    t0 = time.time()
    rec = {"connection": conn, "schema": label, "mode": mode, "question": question}
    try:
        if mode == "ask":
            evs = sse_post("/chat", {"question": question, "connection_id": conn,
                                     "canvas_id": None, "history": [], "session_id": SESSION}, 150)
            by = {}
            for e in evs:
                by[e.get("type")] = e
            rec["headline"] = (by.get("headline") or {}).get("headline")
            rec["narrative"] = (by.get("insight") or {}).get("narrative")
            rec["sql"] = (by.get("sql") or {}).get("sql")
            rec["chart_type"] = (by.get("chart_type") or {}).get("chart_type")
            cols = (by.get("columns") or {}).get("columns") or []
            rows = (by.get("rows") or {}).get("rows") or []
            rec["columns"] = cols
            rec["sample_rows"] = rows[:3]
            rec["n_cols"], rec["n_rows"] = len(cols), len(rows)
            # Insight-level checks
            f = []
            # Only flag a missing average when the SQL has NEITHER AVG() NOR a ratio —
            # AOV-style SUM(...)/COUNT(DISTINCT ...) is the CORRECT way to express an average.
            if (rec["sql"] and re.search(r"\baverage\b|\bavg\b|\bmean\b", question, re.I)
                    and not re.search(r"\bavg\s*\(", rec["sql"], re.I)
                    and "/" not in rec["sql"]):
                f.append("ASK_NOMEAN: 'average' asked but SQL has neither AVG() nor a ratio")
            if not rows and not (by.get("error")):
                f.append("ASK_EMPTY: no rows returned")
            # Headline grounding: headline names a leader/number that the top data row contradicts.
            hl = (rec.get("headline") or "")
            if rows and cols:
                top = rows[0]
                hl_nums = re.findall(r"\$?\s?([\d,]+\.?\d*)\s?([bmk])\b", hl, re.I)
                # crude: if headline asserts a magnitude with a unit but the top row's value
                # differs in order of magnitude, flag for manual review
                if hl_nums and len(top) >= 2 and str(top[-1]).replace('.', '').replace('-', '').isdigit():
                    f.append("HEADLINE_CHECK: headline cites a magnitude — verify it matches the top row")
            rec["flags"] = f
        else:
            evs = sse_post("/investigate", {"question": question, "connection_id": conn,
                                            "canvas_id": None, "skip_cache": True}, 700)
            ada = None
            phase_count = 0
            for e in evs:
                if e.get("type") == "ada_report":
                    ada = e.get("ada_report")
                if e.get("type") == "phase_complete":
                    phase_count += 1
                if e.get("type") == "mode":
                    rec["query_mode"] = e.get("query_mode")
            rec["phase_events"] = phase_count
            if ada:
                rec["ada_report"] = ada
                rec["headline"] = ada.get("headline")
                rec["confidence"] = ada.get("confidence")
                rec["metric"] = ada.get("metric")
                rec["total_change_label"] = ada.get("total_change_label")
                rec["observation_period"] = ada.get("observation_period")
                rec["n_phases"] = len(ada.get("phases") or [])
                rec["n_waterfall"] = len(ada.get("attribution_waterfall") or [])
                # compact per-finding capture for the report
                rec["findings_digest"] = [
                    {"phase": p.get("phase_id"), "title": f.get("title"),
                     "columns": f.get("columns"), "chart_type": f.get("chart_type"),
                     "interp": (f.get("interpretation") or "")[:160]}
                    for p in ada.get("phases", []) for f in (p.get("findings") or [])
                ][:20]
            rec["flags"] = analyze_deep(rec)
    except (urllib.error.URLError, Exception) as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    rec["elapsed_s"] = round(time.time() - t0, 1)
    return rec


def load_done(path):
    done = set()
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done.add((r["connection"], r["mode"], r["question"]))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conn", help="only this connection id")
    ap.add_argument("--mode", choices=["ask", "investigate"], help="only this mode")
    ap.add_argument("--limit", type=int, help="max cases this run (usage pacing)")
    ap.add_argument("--fresh", action="store_true", help="ignore prior JSONL (no resume)")
    args = ap.parse_args()

    done = set() if args.fresh else load_done(OUT_JSONL)
    cases = []
    for conn, battery in BATTERIES.items():
        if args.conn and conn != args.conn:
            continue
        for mode, q in battery:
            if args.mode and mode != args.mode:
                continue
            if (conn, mode, q) in done:
                continue
            cases.append((conn, CONN_LABEL.get(conn, conn), mode, q))
    if args.limit:
        cases = cases[:args.limit]

    print(f"quality_sweep — {len(cases)} new cases (skipped {len(done)} done), session={SESSION}\n")
    out = open(OUT_JSONL, "a")
    results = []
    for conn, label, mode, q in cases:
        print(f"▶ [{label}] {mode}: {q}")
        rec = run_case(conn, label, mode, q)
        out.write(json.dumps(rec) + "\n"); out.flush()
        results.append(rec)
        if rec.get("error"):
            tag = f"  ⚠ ERROR {rec['error'][:60]}"
        elif rec.get("flags"):
            tag = "  ⚑ " + " | ".join(rec["flags"][:4])
        else:
            tag = "  ✓"
        extra = ""
        if mode == "investigate":
            extra = f" [conf={rec.get('confidence')} ph={rec.get('phase_events')} wf={rec.get('n_waterfall')}]"
        print(f"   {rec['elapsed_s']}s → {(rec.get('headline') or '')[:74]}{extra}{tag}\n")
    out.close()

    write_report(OUT_JSONL)
    flagged = [r for r in results if r.get("flags") or r.get("error")]
    print("=" * 72)
    print(f"this run: {len(results)} cases | flagged: {len(flagged)} | report → {OUT_REPORT}")


def write_report(jsonl):
    recs = []
    try:
        with open(jsonl) as fh:
            for line in fh:
                try:
                    recs.append(json.loads(line))
                except Exception:
                    pass
    except FileNotFoundError:
        return
    lines = ["# Quality Sweep Report", ""]
    lines.append(f"Total cases: **{len(recs)}**")
    flagged = [r for r in recs if r.get("flags") or r.get("error")]
    lines.append(f"Flagged: **{len(flagged)}**  ·  Clean: **{len(recs) - len(flagged)}**")
    # flag histogram
    hist = {}
    for r in recs:
        for f in (r.get("flags") or []):
            k = f.split(":")[0].split("[")[0]
            hist[k] = hist.get(k, 0) + 1
        if r.get("error"):
            hist["ERROR"] = hist.get("ERROR", 0) + 1
    if hist:
        lines.append("\n## Defect histogram")
        for k, v in sorted(hist.items(), key=lambda kv: -kv[1]):
            lines.append(f"- **{k}**: {v}")
    lines.append("\n## Flagged cases")
    for r in flagged:
        lines.append(f"\n### [{r.get('schema')}] {r.get('mode')} — {r.get('question')}")
        if r.get("error"):
            lines.append(f"- ERROR: `{r['error'][:200]}`")
        lines.append(f"- headline: {r.get('headline')}")
        if r.get("mode") == "investigate":
            lines.append(f"- confidence={r.get('confidence')} metric={r.get('metric')} "
                         f"obs={r.get('observation_period')} wf={r.get('n_waterfall')}")
        if r.get("sql"):
            lines.append(f"- sql: `{(r.get('sql') or '')[:240]}`")
        for f in (r.get("flags") or []):
            lines.append(f"  - ⚑ {f}")
    with open(OUT_REPORT, "w") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
