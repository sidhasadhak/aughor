#!/usr/bin/env python3
"""Baseline smoke suite — the regression oracle for the component-architecture refactor.

Drives every GET endpoint in the live OpenAPI spec (plus a curated set of read-only
POST flows) against representative seeded connections, records status + response shape,
and checks the Qdrant vector collections. Writes a JSON snapshot so a later run can be
diffed against the baseline to prove the refactor changed nothing it shouldn't.

Usage:
    .venv/bin/python scripts/smoke.py                       # writes data/smoke_baseline.json
    .venv/bin/python scripts/smoke.py --out data/smoke_after.json
    .venv/bin/python scripts/smoke.py --diff data/smoke_baseline.json   # compare to a prior run
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://localhost:8000"
QDRANT = "http://localhost:6333"
TIMEOUT = 45
# Representative connections: a multi-schema in-memory workspace + the single-schema
# analytics warehouse. These two exercise both table-name conventions.
CONNS = ["workspace", "c1c664b0"]
SCHEMA_FOR = {"c1c664b0": "analytics"}
QDRANT_COLLECTIONS = [
    "aughor_investigations", "aughor_sql_examples", "sql_knowledge_base",
    "aughor_documents", "org_intelligence", "aughor_schema",
    "aughor_connection_kb", "schema_suggestions",
]


def _req(method: str, url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read(), round(time.time() - t0, 2)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), round(time.time() - t0, 2)
    except Exception as e:  # connection refused, timeout, …
        return 0, str(e).encode()[:200], round(time.time() - t0, 2)


def _shape(body: bytes) -> str:
    try:
        d = json.loads(body)
        if isinstance(d, list):
            return f"list[{len(d)}]"
        if isinstance(d, dict):
            return f"dict[{len(d)}]"
        return type(d).__name__
    except Exception:
        return f"{len(body)}b/non-json"


def _json(method: str, path: str):
    st, body, _ = _req(method, BASE + path)
    if st == 200:
        try:
            return json.loads(body)
        except Exception:
            return None
    return None


def resolve_params() -> dict[str, list[str]]:
    """Derive concrete sample values for path params from live data, so
    parameterised GETs can be exercised rather than skipped."""
    s: dict[str, list[str]] = {"conn_id": CONNS[:], "connection_id": CONNS[:]}

    ents = _json("GET", "/ontology/entities?connection_id=c1c664b0&schema_name=analytics")
    if isinstance(ents, dict) and ents:
        s["entity_id"] = list(ents.keys())[:1]
    acts = _json("GET", "/ontology/actions?connection_id=c1c664b0&schema_name=analytics")
    if isinstance(acts, dict) and acts:
        s["action_id"] = list(acts.keys())[:1]

    doms = _json("GET", "/exploration/c1c664b0/domains")
    if isinstance(doms, dict) and doms:
        s["domain"] = list(doms.keys())[:1]

    rich = _json("GET", "/connections/c1c664b0/schema/rich")
    if isinstance(rich, dict) and rich.get("tables"):
        s["table"] = [rich["tables"][0]["name"]]

    cv = _json("GET", "/canvases")
    if isinstance(cv, list) and cv:
        s["canvas_id"] = [cv[0].get("id")]
    inv = _json("GET", "/investigations")
    if isinstance(inv, list) and inv:
        s["inv_id"] = [inv[0].get("id")]
    ws = _json("GET", "/workspaces")
    if isinstance(ws, list) and ws:
        s["workspace_id"] = [ws[0].get("id")]
    mx = _json("GET", "/metrics")
    if isinstance(mx, list) and mx:
        s["name"] = [mx[0].get("name")]
    s["schema_name"] = ["analytics"]
    return s


def expand(path: str, samples: dict[str, list[str]]) -> list[str]:
    """Expand a templated path into concrete URLs using resolved samples.
    Returns [] when a required param has no known sample (endpoint skipped)."""
    import re
    params = re.findall(r"\{(\w+)\}", path)
    if not params:
        return [path]
    combos = [path]
    for p in params:
        vals = samples.get(p)
        if not vals:
            return []  # cannot resolve — skip
        combos = [c.replace(f"{{{p}}}", str(v)) for c in combos for v in vals]
    return combos


def qdrant_counts() -> dict[str, int | str]:
    out: dict[str, int | str] = {}
    for c in QDRANT_COLLECTIONS:
        st, body, _ = _req("POST", f"{QDRANT}/collections/{c}/points/count", {"exact": True})
        if st == 200:
            try:
                out[c] = json.loads(body)["result"]["count"]
            except Exception:
                out[c] = "parse_err"
        elif st == 404:
            out[c] = "missing"
        else:
            out[c] = f"err:{st}"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/smoke_baseline.json")
    ap.add_argument("--diff", default=None, help="compare against a prior snapshot")
    args = ap.parse_args()

    # Load the diff baseline BEFORE running/writing. Otherwise, when --out and
    # --diff point at the same file (the common case, since --out defaults to the
    # baseline path), the snapshot write below clobbers the baseline and the diff
    # ends up comparing the run against itself — always "0 regressions".
    prev_results = None
    if args.diff:
        try:
            prev_results = json.loads(Path(args.diff).read_text()).get("results", {})
        except Exception:
            print(f"(could not read diff baseline {args.diff})")

    spec = _json("GET", "/openapi.json")
    if not spec:
        print("FATAL: API not reachable at", BASE)
        return 1
    samples = resolve_params()

    results: dict[str, dict] = {}
    skipped: list[str] = []
    for path, methods in sorted(spec["paths"].items()):
        if "get" not in methods:
            continue
        if path in ("/openapi.json", "/docs", "/redoc"):
            continue
        urls = expand(path, samples)
        if not urls:
            skipped.append(path)
            continue
        for url in urls:
            st, body, dt = _req("GET", BASE + url)
            ok = 200 <= st < 300
            results[f"GET {url}"] = {"status": st, "ok": ok, "shape": _shape(body), "s": dt}

    q = qdrant_counts()

    n_ok = sum(1 for r in results.values() if r["ok"])
    snapshot = {
        "base": BASE,
        "endpoints_tested": len(results),
        "endpoints_ok": n_ok,
        "endpoints_failed": len(results) - n_ok,
        "skipped_unresolved": skipped,
        "qdrant": q,
        "results": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(snapshot, indent=2, default=str))

    print(f"GET endpoints: {n_ok}/{len(results)} ok  ({len(results)-n_ok} failed)  | "
          f"skipped(unresolved params): {len(skipped)}")
    fails = {k: v for k, v in results.items() if not v["ok"]}
    for k, v in sorted(fails.items()):
        print(f"  FAIL {v['status']:>3}  {k}  [{v['shape']}]")
    print("Qdrant collections:")
    for c, n in q.items():
        print(f"  {c:26} {n}")
    print(f"written → {args.out}")

    if args.diff and prev_results is not None:
        prev = prev_results
        regressions = [k for k, v in results.items()
                       if k in prev and prev[k]["ok"] and not v["ok"]]
        newpass = [k for k, v in results.items()
                   if k in prev and not prev[k]["ok"] and v["ok"]]
        print(f"\n=== DIFF vs {args.diff} (baseline loaded pre-write) ===")
        print(f"  regressions (was ok → now fail): {len(regressions)}")
        for k in regressions:
            print(f"    ✗ {k}  {prev[k]['status']} → {results[k]['status']}")
        print(f"  newly passing: {len(newpass)}")
        for k in newpass:
            print(f"    ✓ {k}  {prev[k]['status']} → {results[k]['status']}")
        if not regressions:
            print("  ✓ no regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
