#!/usr/bin/env python3
"""Write / background flow exerciser — the companion to smoke.py.

smoke.py covers the read side (every GET). This drives a curated set of the
write/background flows — connection knowledge-sync, semantic knowledge, metric
create + validate, monitor create + trigger, document upload — and re-checks the
Qdrant collections before/after, so we can confirm the three that start empty
(aughor_documents / org_intelligence / aughor_connection_kb) actually populate
from their feature. Best-effort; uses clearly test-named records.

Usage:  uv run python scripts/flows.py
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://localhost:8000"
QDRANT = "http://localhost:6333"
CONN = "workspace"
QCOLS = [
    "aughor_investigations", "aughor_sql_examples", "sql_knowledge_base",
    "aughor_documents", "org_intelligence", "aughor_schema",
    "aughor_connection_kb", "schema_suggestions",
]


def _req(method, url, body=None, raw=None, headers=None, timeout=60):
    if body is not None:
        raw = json.dumps(body).encode()
        headers = {**(headers or {}), "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=raw, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 0, str(e).encode()[:300]


def jpost(path, body=None, timeout=60):
    st, b = _req("POST", BASE + path, body=body, timeout=timeout)
    try:
        return st, json.loads(b)
    except Exception:
        return st, b[:200].decode("utf-8", "replace")


def qcounts():
    out = {}
    for c in QCOLS:
        st, b = _req("GET", f"{QDRANT}/collections/{c}", timeout=8)
        try:
            out[c] = json.loads(b)["result"]["points_count"] if st == 200 else "missing"
        except Exception:
            out[c] = "missing" if st != 200 else "?"
    return out


def multipart(fields, fname, fcontent, fctype="text/plain"):
    boundary = "----aughorflows" + uuid.uuid4().hex
    pre = "".join(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
        for k, v in fields.items()
    )
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{fname}\"\r\nContent-Type: {fctype}\r\n\r\n")
    body = (pre + head).encode() + fcontent + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


results = []
def rec(name, ok, detail=""):
    results.append((name, ok))
    print(f"  {'✓' if ok else '✗'} {name:30} {detail}")


def main():
    print("=== Qdrant BEFORE ===")
    before = qcounts()
    for c, n in before.items():
        print(f"  {c:26} {n}")

    print("\n=== driving write flows ===")

    st, _ = jpost(f"/connections/{CONN}/knowledge-sync", timeout=120)
    rec("connection knowledge-sync", 200 <= st < 300, f"HTTP {st}")

    st, _ = jpost(f"/semantic/{CONN}/knowledge",
                  {"title": "flows.py test", "body": "Revenue = SUM(totalPrice).",
                   "kind": "note", "tags": ["test"]})
    rec("semantic knowledge add", 200 <= st < 300, f"HTTP {st}")

    mname = "flows_test_metric"
    st, _ = jpost("/metrics", {"name": mname, "label": "Flows Test",
                               "sql": "SELECT COUNT(*) AS c FROM sales_transactions"})
    # 409 = already created by a prior run (idempotent re-run), still a pass.
    rec("metric create", 200 <= st < 300 or st == 409, f"HTTP {st}")
    st, b = jpost(f"/metrics/{mname}/validate?conn_id={CONN}", timeout=90)
    rec("metric validate", 200 <= st < 300, f"HTTP {st} {str(b)[:60]}")

    st, b = jpost("/monitors",
                  {"conn_id": CONN, "name": "Flows Test Monitor",
                   "custom_sql": "SELECT COUNT(*) FROM sales_transactions",
                   "check_cron": "0 9 * * *", "alert_on": "threshold_cross",
                   "warning_threshold": 1, "threshold_direction": "above"})
    mid = (b.get("id") or b.get("monitor_id")) if isinstance(b, dict) else None
    rec("monitor create", 200 <= st < 300, f"HTTP {st} id={mid}")
    if mid:
        st, _ = jpost(f"/monitors/{mid}/trigger", timeout=90)
        rec("monitor trigger", 200 <= st < 300, f"HTTP {st}")

    body, ctype = multipart(
        {"connection_id": CONN}, "flows_test.txt",
        b"Aughor bakehouse notes. Total revenue is SUM(totalPrice) across sales_transactions.",
    )
    st, _ = _req("POST", BASE + "/documents/upload", raw=body,
                 headers={"Content-Type": ctype}, timeout=120)
    rec("document upload", 200 <= st < 300, f"HTTP {st}")

    time.sleep(2)
    print("\n=== Qdrant AFTER (← marks change) ===")
    after = qcounts()
    for c in QCOLS:
        d = f"   ← {before[c]} → {after[c]}" if before[c] != after[c] else ""
        print(f"  {c:26} {after[c]}{d}")

    npass = sum(1 for _, ok in results if ok)
    print(f"\nflows: {npass}/{len(results)} ok")
    print("note: aughor_connection_kb populates only for knowledge connectors "
          "(Confluence/Notion); org_intelligence populates when a canvas insight is "
          "promoted to org — both feature-gated, not failures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
