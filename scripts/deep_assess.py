#!/usr/bin/env python3
"""deep_assess.py — run ONE Deep Analysis (or Insight) end-to-end and capture the FULL
pipeline so the report can be judged qualitatively: intent → decomposition → phases →
per-finding chart/labels → attribution waterfall → recommendations → confidence.

Saves every SSE event to /tmp/assess_{slug}.jsonl (flushed live, survives timeout) and
writes a human-readable judging digest to /tmp/assess_{slug}.md.

Usage: deep_assess.py <conn_id> "<question>" [ask|investigate]
"""
import json
import re
import sys
import urllib.request

BASE = "http://localhost:8000"
conn = sys.argv[1] if len(sys.argv) > 1 else "c1c664b0"
question = sys.argv[2] if len(sys.argv) > 2 else "Why did revenue change recently?"
mode = sys.argv[3] if len(sys.argv) > 3 else "investigate"
slug = re.sub(r"[^a-z0-9]+", "_", question.lower())[:40].strip("_")
EVENTS = f"/tmp/assess_{conn}_{slug}.jsonl"
DIGEST = f"/tmp/assess_{conn}_{slug}.md"


def chart_label_check(f):
    """Heuristic flags on a finding's chart + label mapping."""
    cols = f.get("columns") or []
    ct = f.get("chart_type")
    title = f.get("title") or ""
    notes = []
    if cols:
        cat = cols[0]
        if _toks(title) and _toks(cat) and not (_toks(title) & _toks(cat)):
            notes.append(f"LABEL_DESYNC(title!~catcol:{cat})")
        if cat in ("dimension_value", "value", "col0", "x"):
            notes.append(f"GENERIC_AXIS({cat})")
    if ct in (None, "none") and len(cols) >= 2 and (f.get("rows") or []):
        notes.append("NO_CHART(but tabular data present)")
    share = [c for c in cols[1:] if re.search(r"pct|percent|share|_of_total", c, re.I)]
    nonshare = [c for c in cols[1:] if not re.search(r"pct|percent|share|_of_total|date|month|year", c, re.I)]
    if share and not nonshare:
        notes.append("CHART_PLOTS_SHARE_ONLY")
    return notes


def _toks(s):
    stop = {"by", "per", "of", "the", "net", "total", "average", "avg", "revenue", "sales",
            "value", "amount", "share", "count", "monthly", "over", "time", "loss", "profit"}
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) > 1 and t not in stop}


def main():
    payload = ({"question": question, "connection_id": conn, "canvas_id": None,
                "history": [], "session_id": "assess"} if mode == "ask"
               else {"question": question, "connection_id": conn, "canvas_id": None, "skip_cache": True})
    path = "/chat" if mode == "ask" else "/investigate"
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    evs = []
    out = open(EVENTS, "w")
    subqs, queries = [], []
    ada = None
    with urllib.request.urlopen(req, timeout=900) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line.startswith("data: "):
                continue
            try:
                e = json.loads(line[6:])
            except Exception:
                continue
            out.write(json.dumps(e) + "\n"); out.flush()
            evs.append(e)
            t = e.get("type")
            if t == "subq_answer":
                subqs.append(e)
            elif t == "queries_executed":
                queries.append(e)
            elif t == "ada_report":
                ada = e.get("ada_report")
    out.close()

    L = [f"# Deep Assessment — {mode}", "", f"**Q:** {question}  ·  **conn:** {conn}", ""]
    L.append(f"event types: {sorted({e.get('type') for e in evs})}")

    if ada:
        L += ["", "## Intent / framing",
              f"- metric: **{ada.get('metric')}**",
              f"- confidence: **{ada.get('confidence')}**",
              f"- observation_period: {ada.get('observation_period')}",
              f"- comparison_basis: {ada.get('comparison_basis')}",
              f"- total_change_label: {ada.get('total_change_label')}",
              f"- headline: {ada.get('headline')}",
              f"- executive_summary: {(ada.get('executive_summary') or '')[:400]}"]
        phases = ada.get("phases") or []
        L += ["", f"## Phases ({len(phases)}) — decomposition & analysis"]
        for p in phases:
            L.append(f"\n### {p.get('phase_id')} · {p.get('phase_name')} · {p.get('status')}")
            L.append(f"summary: {(p.get('phase_summary') or '')[:240]}")
            for f in (p.get("findings") or []):
                cols = f.get("columns") or []
                flags = chart_label_check(f)
                L.append(f"- **{f.get('title')}**  [chart={f.get('chart_type')}]"
                         + (f"  ⚑ {flags}" if flags else ""))
                L.append(f"    cols={cols}  rows={len(f.get('rows') or [])}")
                L.append(f"    interp: {(f.get('interpretation') or '')[:200]}")
                kn = f.get("key_numbers") or []
                if kn:
                    L.append(f"    key_numbers: {[(k.get('label'), k.get('value')) for k in kn][:5]}")
        wf = ada.get("attribution_waterfall") or []
        if wf:
            L += ["", "## Attribution waterfall"]
            for w in wf:
                L.append(f"- {w.get('cause')}: {w.get('amount_label')} ({w.get('pct_of_total')}%) "
                         f"controllable={w.get('controllable')} structural={w.get('structural')}")
        recs = ada.get("recommendations") or []
        if recs:
            L += ["", "## Recommendations"]
            for r in recs:
                L.append(f"- {r.get('action')} — impact: {r.get('expected_impact')} "
                         f"(owner={r.get('owner')}, {r.get('timeline')})")
    if subqs:
        L += ["", f"## Decomposition — {len(subqs)} sub-questions"]
        for s in subqs:
            L.append(f"- Q: {s.get('question')}\n    purpose: {s.get('purpose')}\n    answer: {(s.get('answer') or '')[:160]}")
    if mode == "ask":
        by = {e.get("type"): e for e in evs}
        L += ["", "## Insight answer",
              f"- headline: {(by.get('headline') or {}).get('headline')}",
              f"- chart_type: {(by.get('chart_type') or {}).get('chart_type')}",
              f"- columns: {(by.get('columns') or {}).get('columns')}",
              f"- sql: {((by.get('sql') or {}).get('sql') or '')[:300]}",
              f"- narrative: {((by.get('insight') or {}).get('narrative') or '')[:300]}"]

    open(DIGEST, "w").write("\n".join(str(x) for x in L) + "\n")
    print(f"[digest -> {DIGEST}]  [events -> {EVENTS}]")
    print("\n".join(str(x) for x in L[:60]))


if __name__ == "__main__":
    main()
