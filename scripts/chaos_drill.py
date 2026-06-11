#!/usr/bin/env python3
"""WCH-9 chaos drill — the crash-anywhere invariant, executable.

Loops: start the API → create a throwaway connection (copy of samples.duckdb)
→ start an exploration → kill -9 the server at a random moment → restart →
assert recovery:

  I1  no job is left RUNNING without a live process (orphans must be FAILED
      with the "server restart" reason),
  I2  an exploration whose checkpoint was incomplete is auto-resumed
      (a new RUNNING job exists for the connection),
  I3  the journal narrates it (job.orphaned + api.started events present),
  I4  the recovered server actually SERVES — a real query against the
      throwaway connection returns rows (recovery restores service, not just
      state bookkeeping).

Run:  .venv/bin/python scripts/chaos_drill.py [iterations]
Exit: 0 = every iteration recovered; 1 = an invariant failed (details printed).

Deliberately a script, not pytest: it kill -9s real processes and owns ports —
run it on demand (pre-release, post-kernel-change), not in the unit suite.
"""
import json
import random
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).parent.parent
PY = str(REPO / ".venv" / "bin" / "python")
BASE = "http://localhost:8000"
SYSTEM_DB = REPO / "data" / "system.db"


def api(path, method="GET", body=None, timeout=15):
    req = urllib.request.Request(f"{BASE}{path}", method=method)
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def start_server():
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "aughor.api:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            api("/health", timeout=2)
            return proc
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("server did not come up")


def jobs_where(sql, args=()):
    c = sqlite3.connect(SYSTEM_DB)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def drill(iteration: int) -> list[str]:
    failures = []
    seed_copy = Path(f"/tmp/chaos_{iteration}.duckdb")
    shutil.copy(REPO / "data" / "samples.duckdb", seed_copy)
    proc = start_server()
    conn_id = None
    try:
        conn_id = api("/connections", "POST", {
            "name": f"_chaos_{iteration}", "conn_type": "duckdb", "dsn": str(seed_copy),
        })["id"]
        api(f"/exploration/{conn_id}/start", "POST")
        delay = random.uniform(4, 18)
        print(f"  [{iteration}] exploring {conn_id}, killing in {delay:.1f}s …")
        time.sleep(delay)

        proc.kill()  # SIGKILL — no shutdown handlers, the real crash
        proc.wait()
        time.sleep(1)

        frozen = jobs_where(
            "SELECT id FROM jobs WHERE conn_id=? AND state='RUNNING'", (conn_id,))
        proc = start_server()
        time.sleep(6)  # boot recovery + respawn window

        # I1 — the frozen job must now be FAILED with the restart reason.
        for (jid,) in frozen:
            rows = jobs_where("SELECT state, error FROM jobs WHERE id=?", (jid,))
            state, err = rows[0]
            if state != "FAILED" or "server restart" not in (err or ""):
                failures.append(f"I1: job {jid} is {state} ({err!r}), expected FAILED(server restart)")

        # I2 — if the checkpoint was incomplete, a resumed RUNNING job must exist.
        state_file = REPO / "data" / f"exploration_{conn_id}.json"
        phase = "missing"
        if state_file.exists():
            phase = json.loads(state_file.read_text()).get("phase", "pending")
        if phase not in ("complete", "failed", "missing"):
            running = jobs_where(
                "SELECT id FROM jobs WHERE conn_id=? AND state='RUNNING'", (conn_id,))
            if not running:
                failures.append(f"I2: checkpoint at phase={phase} but no resumed RUNNING job")

        # I3 — journal narration.
        orphan_evs = jobs_where(
            "SELECT COUNT(*) FROM events WHERE kind='job.orphaned' AND conn_id=?",
            (conn_id,))[0][0]
        if frozen and orphan_evs == 0:
            failures.append("I3: no job.orphaned event for the crashed run")

        # I4 — the recovered server actually SERVES traffic, not just bookkeeps:
        # a real query against the throwaway connection must return rows.
        try:
            qr = api("/query/run", "POST", {
                "conn_id": conn_id, "sql": "SELECT 1 AS ok", "limit": 1,
                "use_cache": False, "use_bulk": False,
            })
            if not qr or qr.get("error") or not qr.get("rows"):
                failures.append(f"I4: recovered server did not serve a query: {qr}")
        except Exception as exc:
            failures.append(f"I4: query after recovery raised: {exc}")
    finally:
        try:
            if conn_id:
                api(f"/connections/{conn_id}", "DELETE")
        except Exception as exc:
            print(f"  [{iteration}] cleanup warning: {exc}")
        proc.kill()
        proc.wait()
        seed_copy.unlink(missing_ok=True)
    return failures


def main():
    iterations = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    subprocess.run(["pkill", "-f", "uvicorn aughor.api"], capture_output=True)
    time.sleep(2)
    all_failures = []
    for i in range(1, iterations + 1):
        fails = drill(i)
        print(f"  [{i}] {'RECOVERED ✓' if not fails else 'FAILED: ' + '; '.join(fails)}")
        all_failures.extend(fails)
    print(f"\nchaos drill: {iterations} crash(es), "
          f"{'ALL RECOVERED' if not all_failures else f'{len(all_failures)} invariant failure(s)'}")
    sys.exit(1 if all_failures else 0)


if __name__ == "__main__":
    main()
