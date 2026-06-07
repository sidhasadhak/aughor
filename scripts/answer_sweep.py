#!/usr/bin/env python3
"""
answer_sweep.py — fire Insight (/chat) + Deep Analysis (/investigate) across every
connection and capture the structured answer, so we can audit quality, sign
consistency, and question-framing at scale.

Writes data/answer_sweep.jsonl (one record per case) and prints a flagged summary.

Heuristic flags:
  SIGN     — within one report, a quantity's sign/direction is inconsistent
             (waterfall pct sign vs amount_label sign; total_change vs waterfall net).
  FRAME    — a "money/losing" question resolved to a non-money metric (sentiment,
             review, rating) or forced a narrow MoM window with no basis.
  CONF     — confidence is HIGH/MEDIUM despite zero evidence (no rows / all errors).
"""
import json, re, sys, time, uuid, urllib.request, urllib.error

BASE = "http://localhost:8000"
SESSION = "sweep-" + uuid.uuid4().hex[:8]

CASES = [
    # connection_id, label, mode, question
    ("workspace", "bakehouse+ecommerce", "ask",         "Show me total sales by franchise"),
    ("workspace", "bakehouse+ecommerce", "investigate",  "Where are we losing money?"),
    ("c1c664b0",  "beautycommerce",      "ask",         "Show me monthly revenue"),
    ("c1c664b0",  "beautycommerce",      "investigate",  "Where are we losing money?"),
    ("c1c664b0",  "beautycommerce",      "investigate",  "Why did revenue change recently?"),
    ("eed00c42",  "tpch_sf1",            "ask",         "Top 10 customers by revenue"),
    ("eed00c42",  "tpch_sf1",            "investigate",  "Where are we losing money?"),
    ("f809a5c6",  "tpcds_sf1",           "ask",         "Top selling items by sales"),
    ("f809a5c6",  "tpcds_sf1",           "investigate",  "Where are we losing money?"),
    ("9fbaa6f9",  "clickbench",          "ask",         "What are the top 10 most visited pages?"),
]


def sse_post(path: str, payload: dict, timeout: int = 240) -> list[dict]:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    events: list[dict] = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except Exception:
                    pass
    return events


def has_neg(s) -> bool:
    return bool(re.search(r"-\s*\$?\d", str(s or "")))


def is_money_metric(text: str) -> bool:
    return bool(re.search(r"revenue|sales|profit|margin|cost|spend|gmv|income|dollar|\$", (text or ""), re.I))


def is_offtopic_metric(text: str) -> bool:
    return bool(re.search(r"sentiment|review|rating|star|nps|satisfaction", (text or ""), re.I))


def analyze_deep(rec: dict) -> list[str]:
    flags = []
    ada = rec.get("ada_report") or {}
    wf = ada.get("attribution_waterfall") or []
    tcl = ada.get("total_change_label") or ""
    conf = (ada.get("confidence") or "").upper()
    headline = ada.get("headline") or ""
    summary = ada.get("executive_summary") or ""
    phases = ada.get("phases") or []

    # SIGN: amount_label sign disagreeing with pct_of_total sign
    for w in wf:
        pct = w.get("pct_of_total")
        amt = w.get("amount_label") or ""
        if pct is None:
            continue
        if (pct < 0) != has_neg(amt):
            flags.append(f"SIGN: cause '{(w.get('cause') or '')[:30]}' pct={pct} but amount_label='{amt}'")
    # SIGN: total_change vs waterfall net
    if wf:
        net = sum((w.get("pct_of_total") or 0) for w in wf)
        if has_neg(tcl) and net > 5:
            flags.append(f"SIGN: total_change_label '{tcl}' reads negative but waterfall net pct=+{net:.0f}")
        if (not has_neg(tcl)) and re.search(r"\d", tcl) and net < -5:
            flags.append(f"SIGN: total_change_label '{tcl}' reads positive but waterfall net pct={net:.0f}")

    # CONF: confidence vs evidence
    all_findings = [f for p in phases for f in (p.get("findings") or [])]
    rows_seen = sum(1 for f in all_findings if (f.get("columns") and f.get("rows")))
    errored = sum(1 for f in all_findings if f.get("error"))
    if conf in ("HIGH", "MEDIUM") and rows_seen == 0:
        flags.append(f"CONF: {conf} confidence but ZERO findings returned data (errors={errored})")

    # FRAME: money question that resolved off-topic
    q = rec.get("question", "")
    if re.search(r"losing money|profit|margin|revenue", q, re.I):
        target = (ada.get("metric") or "") + " " + headline + " " + summary
        if is_offtopic_metric(headline) or is_offtopic_metric(ada.get("metric") or ""):
            flags.append(f"FRAME: money question → off-topic metric (headline='{headline[:60]}')")
        elif not is_money_metric(target):
            flags.append(f"FRAME: money question but no money metric surfaced (headline='{headline[:60]}')")
    return flags


def run_case(conn, label, mode, question):
    t0 = time.time()
    rec = {"connection": conn, "schema": label, "mode": mode, "question": question}
    try:
        if mode == "ask":
            evs = sse_post("/chat", {"question": question, "connection_id": conn,
                                     "canvas_id": None, "history": [], "session_id": SESSION}, timeout=120)
            by = {}
            for e in evs:
                by[e.get("type")] = e
            rec["headline"] = (by.get("headline") or {}).get("headline")
            ins = by.get("insight") or {}
            rec["narrative"] = ins.get("narrative")
            rec["sql"] = (by.get("sql") or {}).get("sql")
            cols = (by.get("columns") or {}).get("columns") or []
            rows = (by.get("rows") or {}).get("rows") or []
            rec["n_cols"], rec["n_rows"] = len(cols), len(rows)
        else:
            evs = sse_post("/investigate", {"question": question, "connection_id": conn,
                                            "canvas_id": None, "skip_cache": True}, timeout=240)
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
                rec["total_change_label"] = ada.get("total_change_label")
                rec["metric"] = ada.get("metric")
                rec["observation_period"] = ada.get("observation_period")
                rec["comparison_basis"] = ada.get("comparison_basis")
                rec["n_phases"] = len(ada.get("phases") or [])
                rec["n_waterfall"] = len(ada.get("attribution_waterfall") or [])
            rec["flags"] = analyze_deep(rec)
    except urllib.error.URLError as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    rec["elapsed_s"] = round(time.time() - t0, 1)
    return rec


def main():
    out = open("data/answer_sweep.jsonl", "w")
    print(f"answer_sweep — {len(CASES)} cases, session={SESSION}\n")
    summary = []
    for conn, label, mode, q in CASES:
        print(f"▶ [{label}] {mode}: {q}")
        rec = run_case(conn, label, mode, q)
        out.write(json.dumps(rec) + "\n")
        out.flush()
        flagstr = ""
        if rec.get("error"):
            flagstr = f"  ⚠ ERROR {rec['error']}"
        elif rec.get("flags"):
            flagstr = "  ⚑ " + " | ".join(rec["flags"])
        hl = (rec.get("headline") or "")[:80]
        extra = ""
        if mode == "investigate":
            extra = f" [conf={rec.get('confidence')} obs={rec.get('observation_period')} wf={rec.get('n_waterfall')}]"
        print(f"   {rec['elapsed_s']}s → {hl}{extra}{flagstr}\n")
        summary.append(rec)
    out.close()

    # Roll-up
    print("=" * 70)
    flagged = [r for r in summary if r.get("flags") or r.get("error")]
    print(f"cases: {len(summary)}  |  flagged: {len(flagged)}")
    for r in flagged:
        tag = "ERROR" if r.get("error") else ",".join(sorted({f.split(':')[0] for f in r.get('flags', [])}))
        print(f"  [{tag}] {r['schema']} · {r['mode']} · {r['question']}")
    print("\nwritten → data/answer_sweep.jsonl")


if __name__ == "__main__":
    main()
