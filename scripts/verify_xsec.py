#!/usr/bin/env python3
"""Stream a Deep Analysis run and dump the cross_section phase as soon as it lands.
Writes every SSE event to OUT_JSONL immediately so a slow/timed-out run still leaves
partial evidence. Usage: verify_xsec.py <conn_id> "<question>"
"""
import json
import sys
import urllib.request

BASE = "http://localhost:8000"
conn = sys.argv[1] if len(sys.argv) > 1 else "c1c664b0"
question = sys.argv[2] if len(sys.argv) > 2 else "Where are we losing money?"
OUT = f"/tmp/xsec_{conn}.jsonl"


def dump_xsec(phase):
    print(f"\n=== CROSS_SECTION: {phase.get('phase_name')} | {phase.get('status')}")
    print("summary:", (phase.get("phase_summary") or "")[:200])
    for f in phase.get("findings", []):
        cols = f.get("columns") or []
        row0 = (f.get("rows") or [[]])[0]
        title = f.get("title") or ""
        dim_ok = (cols[0].lower() in title.lower()) if cols else None
        print(f"\n  • TITLE: {title}")
        print(f"    columns: {cols}")
        print(f"    row[0] : {row0}")
        print(f"    CHECKS  dim_in_title={dim_ok} "
              f"metric_total_primary={(cols[1]=='metric_total') if len(cols)>1 else None} "
              f"pct_stripped={'pct_of_total' not in cols} avg_kept={'avg_per_record' in cols}")
        print(f"    interp : {(f.get('interpretation') or '')[:220]}")
        kn = f.get("key_numbers") or []
        if kn:
            print(f"    key_nums: {[(k.get('label'), k.get('value')) for k in kn][:4]}")


def main():
    req = urllib.request.Request(
        BASE + "/investigate",
        data=json.dumps({"question": question, "connection_id": conn,
                         "canvas_id": None, "skip_cache": True}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    out = open(OUT, "w")
    ada = None
    seen_xsec = False
    print(f"Deep Analysis: {question!r} on {conn}")
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line.startswith("data: "):
                continue
            try:
                e = json.loads(line[6:])
            except Exception:
                continue
            out.write(json.dumps(e) + "\n"); out.flush()
            t = e.get("type")
            if t == "phase_complete":
                ph = e.get("phase") or {}
                if ph.get("phase_id") == "cross_section":
                    dump_xsec(ph); seen_xsec = True
            elif t == "ada_report":
                ada = e.get("ada_report")
            elif t == "mode":
                print("query_mode:", e.get("query_mode"))
    if ada:
        print("\n=== FINAL ADA REPORT ===")
        print("confidence:", ada.get("confidence"), "| metric:", ada.get("metric"))
        print("headline:", (ada.get("headline") or "")[:160])
        if not seen_xsec:
            for ph in ada.get("phases", []):
                if ph.get("phase_id") == "cross_section":
                    dump_xsec(ph)
    print(f"\n[events -> {OUT}]")


if __name__ == "__main__":
    main()
