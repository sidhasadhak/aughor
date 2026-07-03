"""Missimi quality eval (Option B: 15 Insight + 15 Deep Analysis).

Drives the REAL pipeline via the running API (/chat for Insight, /investigate for Deep),
parses the SSE stream, and records SQL / columns / sample rows / chart_type / narrative /
route / errors / elapsed for each question to a JSONL file. Sequential, fail-open per Q.
"""
import json
import time
import urllib.request

BASE = "http://localhost:8000"
CONN = "workspace"
CANVAS = "c4a225a7"  # Missimi Retail & Operations
OUT = "/tmp/missimi_eval_results.jsonl"

INSIGHT = [
    "What is the total delivered revenue?",
    "What is the average order value broken down by payment type?",
    "What is the average order value broken down by status?",
    "What is the gross margin rate by product category?",
    "What are the top 10 products by revenue?",
    "What is the overall repeat purchase rate?",
    "Show monthly delivered revenue for 2025.",
    "What is the marketing ROAS by channel?",
    "What is the customer acquisition cost (CAC) by channel?",
    "What is the distribution of review scores?",
    "What is delivered revenue by customer country (top 10)?",
    "What is freight cost as a percent of order value by country?",
    "How many orders are there by status?",
    "What is the average review score by product category?",
    "What is inventory turnover by month?",
]

DEEP = [
    "Why is the repeat purchase rate declining?",
    "Which marketing channel has the best ROAS and why?",
    "Why are some orders marked shipped but never delivered?",
    "What is driving gross margin differences across product categories?",
    "Why is average order value higher for some payment types than others?",
    "Which products have high revenue but a low repeat-customer rate?",
    "Are low review scores (<=2) concentrated in specific countries or product categories?",
    "What is causing freight cost to vary across countries?",
    "Why did delivered revenue change month over month in 2025?",
    "Which customer segments drive the most lifetime value?",
    "Is there a relationship between delivery time and review score?",
    "What is driving CAC differences across marketing channels?",
    "Which warehouses or regions show inventory turnover problems?",
    "Why are certain orders cancelled rather than delivered?",
    "What explains the difference between high-AOV and low-AOV orders?",
]


def _post_sse(path: str, payload: dict, timeout: int = 360):
    """POST and yield parsed SSE events (dicts)."""
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        buf = ""
        for raw in resp:
            buf += raw.decode("utf-8", "replace")
            while "\n\n" in buf:
                chunk, buf = buf.split("\n\n", 1)
                for line in chunk.splitlines():
                    if line.startswith("data: "):
                        try:
                            yield json.loads(line[6:])
                        except Exception:
                            pass


def run_one(mode: str, q: str) -> dict:
    t0 = time.time()
    rec = {"mode": mode, "question": q, "events": [], "error": None,
           "sql": None, "columns": None, "rows": None, "row_count": None,
           "chart_type": None, "headline": None, "narrative": None,
           "query_mode": None, "report": None}
    try:
        if mode == "insight":
            path, payload = "/chat", {"question": q, "connection_id": CONN, "canvas_id": CANVAS, "history": []}
        else:
            path, payload = "/investigate", {"question": q, "connection_id": CONN, "canvas_id": CANVAS,
                                             "skip_cache": True, "insight_id": None, "deep": False}
        for ev in _post_sse(path, payload):
            t = ev.get("type")
            rec["events"].append(t)
            if t == "sql": rec["sql"] = ev.get("sql")
            elif t == "columns": rec["columns"] = ev.get("columns")
            elif t == "rows":
                rows = ev.get("rows") or []
                rec["row_count"] = len(rows); rec["rows"] = rows[:5]
            elif t in ("headline", "answer"): rec["headline"] = ev.get("headline") or ev.get("text")
            elif t == "chart_type": rec["chart_type"] = ev.get("chart_type")
            elif t == "insight": rec["narrative"] = ev.get("narrative")
            elif t == "mode": rec["query_mode"] = ev.get("query_mode")
            elif t == "ada_report":
                r = ev.get("ada_report") or {}
                rec["report"] = {"headline": r.get("headline"), "sql": r.get("sql"),
                                 "narrative": r.get("narrative") or r.get("summary"),
                                 "chart_type": r.get("chart_type"),
                                 "key_numbers": r.get("key_numbers"),
                                 "confidence": r.get("confidence")}
            elif t == "explore_report":
                r = ev.get("explore_report") or {}
                rec["report"] = {"narrative": r.get("narrative"), "subq": len(r.get("sub_questions") or [])}
            elif t == "error": rec["error"] = ev.get("message")
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    rec["elapsed_s"] = round(time.time() - t0, 1)
    return rec


def main():
    open(OUT, "w").close()  # truncate
    plan = [("insight", q) for q in INSIGHT] + [("deep", q) for q in DEEP]
    for i, (mode, q) in enumerate(plan, 1):
        print(f"[{i}/{len(plan)}] {mode:7} … {q[:60]}", flush=True)
        rec = run_one(mode, q)
        with open(OUT, "a") as f:
            f.write(json.dumps(rec) + "\n")
        tag = rec["error"] or f'{rec.get("query_mode") or mode} · {rec["elapsed_s"]}s · {rec.get("row_count")} rows'
        print(f"       -> {tag}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
