# Install accuracy — verification findings and remediation plan (2026-08-18)

**Status:** all four PRs landed · **Scope:** README Quick Start, CONTRIBUTING setup, first-boot behaviour,
the `export` extra's degradation contract.

The Quick Start was executed verbatim on a clean container and every documented claim around it
was tested. **The install works** — both commands succeed and you get a running app. Eleven
documented claims around it do not hold, one of which is a product bug rather than a doc error.

This document records what was measured, the two product decisions that shape the fix, and a
per-item plan with the patch, the test that proves it, and the risk.

---

## 1. How this was verified

| | |
|---|---|
| Platform | Linux x86-64, 4 cores, clean container, repo cloned fresh |
| Toolchain | uv 0.8.17 · CPython 3.11.15 · Node 22.22.2 · npm 10.9.7 |
| Commit | `4fc037d` |
| Method | ran each documented command; probed each documented endpoint; measured each documented number |

Everything below is a measurement, not a reading of the code. Where a number is quoted it was
produced on the machine described above and can be re-run.

### What already works — do not regress it

`uv sync --all-extras` (exit 0, 194 packages) → `uv run aughor up` (auto-ran `npm install`,
885 packages in 26 s) → API `:8000` and web `:3000` both serving 200. Also confirmed working
exactly as documented: `/docs`; the busy-port refusal (names the owning pid, refuses to kill,
exits 1, and the running servers survive); `--api-port` / `--web-port` including the automatic
`NEXT_PUBLIC_API_URL` hand-off to the web app; `--api-only`; `./start.sh --stop`; the manual
uvicorn startup path; `cp .env.example .env` (safe — one active line); and all four CI checks
from CONTRIBUTING (ruff at zero, `tsc --noEmit`, the three lint gates, `gen:api` with no drift).
The frontend builds in 13.9 s. The `semantic` and `fastread` extras degrade cleanly.

---

## 2. Decisions that shape this plan

### D1 — No dataset ships by default

**Decision (owner's stand): nothing is seeded on first boot.**

This plan adopts that, and the evidence supports it more strongly than expected:

- It is the **sole cause** of the broken first-boot summary (W4). Seeding `data/aughor.duckdb`
  takes **98.2 s** and blocks application startup; the boot health probe waits 30 s and gives up.
- It is a **surprise write**. A fresh install silently fabricates 72,000 rows of synthetic
  revenue. For a platform whose thesis is evidence-backed, checkable numbers, materialising
  realistic-looking business data unasked is off-message, and "Fixture DB (demo)" sits in the
  connection list next to real ones.
- **Serving deployments pay for it.** The whole extras split exists to fit a size-limited target;
  those deployments currently pay 3.7 MB and ~98 s of boot CPU for a demo no tenant wants.

**Challenge — do not delete it, make it opt-in.** The stand is "nothing ships as *default*",
and that is right. Removing the capability entirely would be a different and worse change:

1. **The empty first run gets very empty.** Combined with W2 (no default model ships either), a
   new user following the Quick Start would open `localhost:3000` to no data *and* no model —
   two dead ends at once, with nothing to demonstrate the product on.
2. **The scenario is deliberate work, not filler.** `aughor/demo/scenario.py` encodes an APAC
   payment-gateway outage with an NA-promo red herring, and the code comment says the previous
   uniform-noise seed was replaced precisely because it "made the first-run Briefing narrate a
   non-finding (W14)". It is a designed demonstration of the differentiator — finding a real
   cause and rejecting a plausible decoy. That asset should survive.
3. **The 98 s is a defect, not a cost of the dataset.** `daily_revenue` inserts 72,000 rows with
   a row-by-row `executemany` into an OLAP engine. Chunked multi-row `VALUES`, measured on the
   same shape: **45.7 s → 1.7 s (27×)**. Once fixed, opting in is effectively instant, so keeping
   it available costs the default path nothing.

**Recommendation:** default-off, one command or one click on. Keep `aughor seed`, keep the
scenario, and add a "Load demo data" action to the empty state alongside "Connect your data".

**Load-bearing consequence to decide with this.** `aughor/db/registry.py:137` lists the `fixture`
connection **unconditionally**, whether or not the file exists. Auto-seeding is what currently
keeps that honest — `ensure_fixture_db`'s own docstring says it was added because "a fresh
install had a broken 'Fixture DB (demo)' connection". Turning seeding off without touching the
registry re-creates exactly that bug. See W4b.

### D2 — Ollama stays the default; the provider list stays as it is

Ollama on localhost remains the default backend. The Groq / Together / Anthropic / Gemini /
OpenRouter blocks in `.env.example` and their mention in the README stay exactly as they are —
all five were verified present and correct.

The **only** LLM-related doc change in this plan is deleting the false sentence claiming built-in
default *models* ship (W2). Nothing about backend choice, provider coverage, or the free-tier note
changes. Reviewers: do not let a W2 edit shrink the provider list.

---

## 3. Workstreams

Grouped into four PRs. Item numbers cross-reference the verification report.

### PR-1 — The export extra's degradation contract (bug)

#### W1. `/investigations/{id}/export` returns 500, not the documented 501

**Severity:** high — this is the only item where the product misbehaves rather than the docs
misdescribe it. It breaks a contract the README states twice.

**Evidence.** On a serving-core install (`uv sync`, exactly as documented):

```
GET /investigations/{id}/export?format=pdf
→ HTTP 500  {"error":"internal_error","request_id":"…"}
→ server log: ModuleNotFoundError: No module named 'matplotlib'
```

README states: "`/investigations/{id}/export` answers **501** naming the extra" and "Nothing here
fails hard: each feature checks for its dependency and degrades with a message naming the install
command." Neither holds. The comment at `aughor/routers/investigations.py:5335` even says "A 500
would send the operator hunting a bug" — which is what ships.

**Root cause.** `aughor/export/__init__.py:14` imports `.document` *above* the guard;
`.document:16` imports `.charts`; `.charts:28` imports matplotlib at module scope. The guard at
lines 24–32 only ever protects `.pdf` and `.slides`, and is never reached.

**Fix.**

```diff
--- a/aughor/export/__init__.py
-from .document import ExportDoc, build_export_doc
-
 # The renderers carry the heavy end of the dependency tree — reportlab, python-pptx and
 # matplotlib — and none of it is on the request path until someone actually asks for a file.
 try:
+    # `.document` imports `.charts`, which imports matplotlib at module scope. It is part of
+    # the extra's dependency closure and belongs INSIDE this guard, not above it.
+    from .document import ExportDoc, build_export_doc
     from .pdf import render_pdf
     from .slides import render_pptx
     EXPORT_AVAILABLE = True
     _EXPORT_IMPORT_ERROR = ""
 except ImportError as _exc:                       # pragma: no cover — depends on install
+    ExportDoc = build_export_doc = None           # type: ignore[assignment,misc]
     render_pdf = render_pptx = None               # type: ignore[assignment]
     EXPORT_AVAILABLE = False
     _EXPORT_IMPORT_ERROR = str(_exc)
```

Safe: `from __future__ import annotations` is already in force, and `export_report` checks
`EXPORT_AVAILABLE` (line 63) before touching `build_export_doc` (line 68).

**Second layer — the router.** `investigations.py:5319` imports outside its own `try` (which
opens at 5329), so any future import-time breakage still escapes as a 500. Guard the import
separately, before `check_owner`:

```python
try:
    from aughor.export import ExportUnavailable, export_report
except ImportError as exc:                     # the extra's own deps are missing
    raise HTTPException(status_code=501, detail=(
        "Report export needs the 'export' extra (reportlab, python-pptx, matplotlib). "
        f"Install it with:  uv sync --extra export   —  underlying error: {exc}"))
```

**Tests.** The existing ratchet stayed green through this bug: `test_serving_footprint.py` checks
only the API's **boot** closure, and matplotlib is imported at **handler** time. Add the missing
half — a subprocess import with `matplotlib`/`reportlab`/`pptx` blocked by a `MetaPathFinder`
whose `find_spec` raises `ImportError`, asserting `import aughor.export` succeeds with
`EXPORT_AVAILABLE is False`; plus an endpoint test that monkeypatches `EXPORT_AVAILABLE = False`
against a real investigation and asserts 501 with the extra named in the detail.

**Also in scope (one-line each).** The install command in the degradation messages disagrees with
the README: `export/__init__.py:66`, `semantic/vector_store.py:97` and `knowledge/documents.py`
say `uv pip install -e '.[extra]'`, the README says `uv sync --extra <name>`. Align on the README
form.

**Risk:** low. Behaviour with the extra installed is unchanged (verified: `EXPORT_AVAILABLE` is
`True` after `uv sync --all-extras`).

---

### PR-2 — First-boot honesty (W3, W4)

These are one user-facing complaint: the boot summary tells a new user things that are not true.

#### W3. The summary reports the LLM "ready" when nothing is configured or reachable

**Evidence.** On a box with **no Ollama installed at all** (`:11434` unreachable) and no model
configured, `aughor up` printed:

```
LLM   ollama · ? · ready
```

`resolve_binding('coder')` returns `('ollama', '', …)` — the `?` is an empty model name — and
`require_model` raises *"Nothing is assumed — this deployment ships no default model."*
`_llm_readiness` (`aughor/routers/system.py:15`) sets `ready = key_present`, and Ollama is not in
`NEEDS_KEY`, so `ready` is unconditionally `True`.

**Fix — no network call needed.** An empty model is knowably not ready:

```diff
--- a/aughor/routers/system.py
     key_present = backend not in provider.NEEDS_KEY or bool(provider._active_key(backend))
-    out["key_present"] = out["ready"] = key_present
+    out["key_present"] = key_present
+    # A backend with no model resolves to "" and every request raises NoModelConfigured.
+    # That is not ready, and saying so costs no network call — /health stays instant.
+    out["ready"] = bool(key_present and model)
+    out["reason"] = None if out["ready"] else ("no_key" if not key_present else "no_model")
```

The CLI's failure text hardcodes the wrong cause (`cli.py:197`, "API key missing" — wrong for a
missing model):

```diff
--- a/aughor/cli.py
-            console.print(f"  LLM   {backend} · {model} · [red]not ready (API key missing)[/red]")
+            why = {"no_key": "API key missing",
+                   "no_model": "no model configured"}.get(llm.get("reason"), "not configured")
+            console.print(f"  LLM   {backend} · {model} · [red]not ready ({why})[/red]")
```

Also point the remediation line at Settings ▸ Models / `AUGHOR_CODER_MODEL` for the `no_model`
case. Net effect: `ollama · ? · ready` becomes `ollama · ? · not ready (no model configured)`,
which is both true and actionable.

**Reachability is a separate axis** and stays out of `/health` by design (its docstring requires
the endpoint stay instant). A *configured* model on a dead Ollama will still report ready.
Either soften the README to "shows whether your LLM is **configured**", or add an opt-in
`GET /health?probe=llm` with a 2 s timeout. Recommend the README wording now, the probe later.

**Test:** parametrise `_llm_readiness` over (no key / no model / both present) and assert
`ready` and `reason`; assert the CLI renders each reason.

#### W4. The boot summary the Quick Start promises never appears on a real first boot

**Evidence.** Measured first run:

```
08:06:11  Started server process
08:06:12  Seeding fixture DB (aughor.duckdb) — SaaS outage-scenario demo…
08:07:29  Samples DB validated: 5 tables
08:07:33  Application startup complete            ← 82 s after launch
```

The CLI waits 30 s (`cli.py:160`) and prints *"/health did not answer within 30 s — the API may
still be starting"* instead of the summary. Warm boots print it correctly. The one run where a
newcomer most needs the summary is the only run that misses it.

**Root cause is sharper than the timeout.** `aughor/api.py:116` does `await _setup_samples()`
inside the lifespan, so seeding blocks startup — directly contradicting that function's own
comment at `api.py:364`: *"Run synchronous DB seeding off the event loop so startup returns
instantly."* It does not. The codebase's own pattern for background work is
`asyncio.create_task` (`api.py:594`, `595`, `630`, `656`).

**Under D1 this mostly dissolves** — with nothing seeded by default, first boot is a warm boot.
Three fixes still apply, in priority order:

- **W4a — stop blocking the lifespan.** Whatever seeding remains (opt-in, or a user re-seeding)
  must not gate `Application startup complete`. Either `asyncio.create_task(_setup_samples())`
  matching the surrounding convention, or run it from the CLI's seed path rather than the API's.
  Fixes the class of bug, not just this instance.
- **W4b — make the registry honest (required by D1).** `registry.py:137` advertises the `fixture`
  connection unconditionally; with no auto-seed the file is absent and opening it read-only
  raises `IOException`. Gate it:
  ```diff
  -    if BUILTIN_ID not in hidden:
  +    # Only advertise the demo connection once it has actually been seeded — an unseeded
  +    # fixture is a broken connection, which is what auto-seeding used to paper over.
  +    if BUILTIN_ID not in hidden and fixture_db_path().exists():
  ```
  Pair with an empty-state CTA offering "Load demo data" (runs `aughor seed`) next to
  "Connect your data".
- **W4c — make seeding fast, so opting in is pleasant.** Replace the 72,000-row `executemany` in
  `demo/scenario.py:152` with chunked multi-row `VALUES` (~2,000 rows/statement). Measured on the
  same shape: **45.7 s → 1.7 s**. Zero new dependencies; determinism is unaffected (the seeded
  `random.Random(SEED)` draw order does not change).

**Then W4d — keep a safety net.** Even with seeding off the startup path, scale the health wait to
the work and stop calling it an error. Add `notice` / `notice_after` params to `_wait_for_health`
and print an interim line after ~12 s. `is_alive` already short-circuits a dead API, so a longer
ceiling costs nothing on the failure path.

**Docs.** The Quick Start's "First boot auto-seeds a synthetic demo dataset and registers it as a
connection, so there is something to explore before you connect anything real" must be rewritten
for D1 — describe the opt-in instead.

**Risk:** medium — this is the only workstream that changes default product behaviour. Tests and
fixtures that assume `data/aughor.duckdb` exists need auditing; `ensure_fixture_db` is idempotent
and only seeds when absent, so existing installs are untouched.

---

### PR-3 — Documentation truth pass (W2, W5, W7, W8, W10)

Each is a text edit; grouped so they land as one reviewable diff.

#### W2. README promises default models that were deliberately deleted

`README.md:82` — *"The built-in default models are Ollama cloud-tier (they need `ollama signin`)"*.
They were removed on 2026-08-15 (commits `b96838d`, `54482ae`). `NoModelConfigured`'s docstring
(`provider.py:89`) records why: the shipped guesses about other vendors' catalogues went stale
silently and the app "kept running and produced nothing". A user following the Quick Start today
gets an app that boots, claims the LLM is ready (W3), and fails on the first question.

**Replacement text** (per D2 — Ollama default and the provider list are untouched):

> **Pick your LLM.** Aughor defaults to [Ollama](https://ollama.com) on localhost, but **ships no
> default model** — nothing is assumed, so you must name one before your first question. Choose it
> in **Settings → Inference** (it lists what your backend actually serves), or set
> `AUGHOR_CODER_MODEL` / `AUGHOR_NARRATOR_MODEL` in `.env`. For a fully-local run:
> `ollama pull qwen2.5-coder:14b`, then pin it (see below).

The following sentence — hosted APIs, `AUGHOR_BACKEND`, and the Groq / Together / Anthropic /
Gemini / OpenRouter blocks with the free-tier note — **stays verbatim**.

#### W5. Install-size figures are 1.6–2× understated and mutually inconsistent

| Measurement | README | Measured |
|---|---|---|
| Serving core (`uv sync`) | 225 MB | **362 MB** |
| All extras (`uv sync --all-extras`) | 622 MB | **1.2 GB** |

Three incompatible figure-sets exist in the tree: README 225/622, `pyproject.toml` 102/121/~1.1 GB,
`test_serving_footprint.py` 102/121/312. They are not measuring the same thing — `du -sh .venv` is
not the import closure — and nothing says which is which. `pyproject`'s "~1.1 GB" matches the
measured venv; the README's 622 MB matches nothing.

**Fix:** label what each number measures and correct the README:

> A bare `uv sync` installs the **serving core** only — a ~360 MB venv rather than ~1.2 GB
> (measured with `du -sh .venv` on linux-x86-64 / CPython 3.11; the API's *import closure* is far
> smaller — see `tests/unit/test_serving_footprint.py`) —

**Durable fix:** add `scripts/measure_footprint.py` printing both numbers, so they are reproducible
rather than folklore that drifts again.

#### W7. Test count and runtime are stale

Measured: **7,024 passed, 32 skipped, 6 deselected, 2 failed (W6), in 11 m 49 s** serial on 4 cores.

- `4,700+` → `7,000+` in `README.md:285`, `README.md:341`, and `.github/workflows/ci.yml:56`.
- `~3 minutes`: either state the hardware honestly, or **make it true** — add `pytest-xdist` to the
  dev extra and document `uv run pytest -q -n auto -m "not e2e and not eval"`. There is no
  `addopts` and no xdist today, so the suite is fully serial. Audit order-dependent suites first.

#### W8. The CI badge URL is invalid

`README.md:8` (the only occurrence) points at `/notifications/workflows/ci.yml`, which is not a
GitHub path — both the badge image and its link are broken.

```diff
-    <a href="https://github.com/sidhasadhak/aughor/notifications/workflows/ci.yml"><img src="https://github.com/sidhasadhak/aughor/notifications/workflows/ci.yml/badge.svg" alt="CI" /></a>
+    <a href="https://github.com/sidhasadhak/aughor/actions/workflows/ci.yml"><img src="https://github.com/sidhasadhak/aughor/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
```

#### W10. Node floor is understated

`next@16.2.6` declares `engines: {node: ">=20.9.0"}`; README says "Node 20+" and CONTRIBUTING says
"20". Node 20.0–20.8 would fail. Update both, and make it enforceable by adding
`"engines": {"node": ">=20.9.0"}` to `web/package.json` (currently absent). CI's `node-version: "20"`
resolves to the latest 20.x, so it stays green.

---

### PR-4 — Repeatability (W6, W9, W11)

#### W6. "Hermetic, no network" is false

CONTRIBUTING claims the backend suite is "hermetic, no network, no LLM". Two tests download DuckDB
extensions from `extensions.duckdb.org` and fail on a network-restricted machine — the only two
failures in the entire run:

- `tests/unit/test_upload_file_formats.py::test_xlsx_reads` — `excel`
- `tests/integration/test_aughor_ops_connection.py::test_listed_and_queryable_when_flag_on` —
  `sqlite_scanner` (its ATTACH failure is swallowed by `tolerate`, so the test fails late with a
  confusing empty-schema assertion rather than naming the cause)

**Fix (a) — skip only when genuinely unavailable.** This respects the rule `test_xlsx_reads`'
docstring lays down — it deliberately avoids `importorskip` because "a test that never runs would
not have caught the bug it exists for". The helper below runs everywhere the extension is
reachable or cached (CI included) and skips only when it truly cannot be had:

```python
@pytest.fixture(scope="session")
def duckdb_extension():
    def _ensure(name: str):
        try:
            duckdb.connect(":memory:").execute(f"INSTALL {name}; LOAD {name};")
        except duckdb.Error as exc:
            pytest.skip(f"DuckDB extension {name!r} unavailable (offline?): {exc}")
    return _ensure
```

Call `duckdb_extension("excel")` and `duckdb_extension("sqlite_scanner")` at the top of the two
tests — the second one turns a misleading assertion failure into a named skip.

**Fix (b) — correct CONTRIBUTING:** "hermetic and offline, apart from two tests that fetch a DuckDB
extension on first run; they skip automatically when it isn't reachable."

Optionally pre-cache extensions in CI via `DUCKDB_EXTENSION_DIRECTORY` so the skip never fires there.

#### W9. The committed `uv.lock` is stale, so the documented install dirties every tree

`uv lock --check` against the committed lock: *"The lockfile at `uv.lock` needs to be updated."*
`pyproject.toml` requires `langfuse>=4,<5`; the lock records `>=2.0.0`. Running the documented
`uv sync --all-extras` rewrites it, leaving `git status` dirty on a fresh clone.

- **Fix:** run `uv lock`, commit.
- **Prevent recurrence:** change `.github/workflows/ci.yml:72` from `--frozen` to `--locked`.
  `--frozen` installs from a stale lock without complaint, which is exactly why this drifted
  unnoticed; `--locked` fails the build. Expect CI red until the re-lock lands.
- **npm side:** `npm install` under npm 10.9.7 strips `libc` fields written by a newer npm
  (30 deletions in `web/package-lock.json`). Add `"packageManager": "npm@10.9.7"` to
  `web/package.json` so everyone writes the same format.

#### W11. `./start.sh --stop` uses an over-broad `pkill`

`pkill -f "next dev"` (start.sh:23) matches any process whose command line contains that string —
it killed the verifying shell twice during this exercise.

```diff
-  pkill -f "uvicorn aughor.api" 2>/dev/null && echo "API stopped" || echo "API was not running"
-  pkill -f "next dev"           2>/dev/null && echo "Web stopped" || echo "Web was not running"
+  pkill -u "$(id -u)" -f "[u]vicorn aughor.api" 2>/dev/null && echo "API stopped" || echo "API was not running"
+  pkill -u "$(id -u)" -f "[n]ext dev -p"        2>/dev/null && echo "Web stopped" || echo "Web was not running"
```

The `[n]` form stops the pattern matching the `pkill` invocation itself; `-p` narrows to the actual
dev server; `-u` confines it to the current user. **Sturdier alternative:** have `aughor up` write
child PIDs to `data/.aughor.pids` and have `--stop` read that file — no pattern matching at all.

---

## 4. Sequencing

| PR | Contents | Size | Risk | Status |
|---|---|---|---|---|
| **PR-1** | W1 export degradation + the missing handler-time ratchet test | small | low | **landed** |
| **PR-2** | W3 readiness, W4a–d first-boot + D1 default-off | medium | **medium** — changes default behaviour | **landed** |
| **PR-3** | W2, W5, W7, W8, W10 — docs truth pass | medium | none | **landed** |
| **PR-4** | W6, W9, W11 — repeatability | small | low | **landed** |

### Measured after PR-2

| | Before | After |
|---|---|---|
| Fresh first boot to the summary | 82 s, and the summary never printed | **6 s**, summary printed |
| Seeding the demo scenario | 98.2 s | **2.3 s** — byte-identical content |
| Backend suite wall clock | 11 m 56 s | **10 m 23 s** (the seed runs once per session) |
| Data written by a fresh boot | 3.7 MB, 72,000 synthetic rows | **none** |

### Corrected figures (PR-3)

Measured with the new `scripts/measure_footprint.py`, which exists because three
figure-sets had drifted apart without saying which size each meant:

| | README claimed | Measured |
|---|---|---|
| Serving-core venv | 225 MB | **~350 MB** |
| All-extras venv | 622 MB | **~1.2 GB** |
| API import closure (a *different* measurement) | — | **106 MB**, 44 packages |
| Backend tests | 4,700+ | **7,033** |
| Suite wall clock | ~3 min | **10–12 min**, serial on 4 cores |

### Changed during PR-4 — the npm half of W9

W9 proposed pinning `packageManager` to `npm@10.9.7`. On inspection that is the wrong
call and it was **not** done. `web/package-lock.json` was written by npm 11, which records
a `libc` field on platform-specific optional deps; npm 10 strips those on any
`npm install`. Pinning 10.9.7 would therefore force the lockfile into npm-10 format and
discard that metadata, and pinning npm 11 contradicts CI's install step, which is written
against npm 10 on purpose (`.github/workflows/ci.yml`). `npm ci` passes either way, so CI
is unaffected and the churn is contributor-side only. Choosing which npm the project
targets is a maintainer decision, so the hazard was documented in CONTRIBUTING instead.

**Resolved 2026-08-18 (owner's call): pinned to npm 10.** `web/package.json` now
declares `"packageManager": "npm@10.9.7"` (what Node 20 bundles and CI runs — zero CI
changes), the lockfile was regenerated once into npm-10 canonical form (the `libc`
fields are gone; a harmless install-time hint), and a second regeneration was verified
to be a no-op. `corepack enable` gives every contributor that exact npm; the CONTRIBUTING
note now describes the pin instead of the churn.

The uv half was done: the lockfile is re-locked, and both CI sync steps moved from
`--frozen` to `--locked` so a stale lock fails the build rather than riding along.

### PR-6 — the two loose ends (landed)

**The faux-LLM flake is fixed structurally.** `faux.calls()` returned refused requests
alongside served ones, so a background thread left over from an earlier test (a
scheduler heartbeat, a kernel task) firing one unscripted completion mid-test made an
unrelated `(call,) = faux_llm.calls()` unpack two entries. A stray is by definition
unscripted → refused, so `calls()` now returns served requests only and `refusals()`
carries the rest; the refusal is still raised loudly to its own caller. The regression
test spawns a real stray thread and fails on the previous code.

**The npm decision** is recorded above under "Changed during PR-4".

### PR-5 — the in-app "Load demo data" CTA (landed)

Deferred from PR-2 and now shipped whole, per CONTRIBUTING's "build → wire → test →
leverage": `POST /connections/demo` (idempotent, gated at `CONNECTION_CREATE` like
adding a connection) plus the first-run funnel's step 2, which previously promised a
"bundled BeautyCommerce sample workspace" and — after D1 — opened an empty Workspace.

Driving it in a real browser found two client-side defects that no unit test would
have caught, because the seed and the API were correct throughout:

1. **The Catalog tree never refetched.** `CatalogScreen` loads a server-built tree in
   `useEffect(…, [workspaceId])` and stays mounted behind the other tabs, so a
   connection added while it was mounted never appeared. This affected the ordinary
   **+ Add** flow too — a pre-existing bug, not one D1 introduced.
2. **The workspace list went stale.** The Catalog renders `wsConnections`, filtered by
   the active workspace's membership. Refreshing connections alone left the new
   connection filtered out, so the demo looked like it had not loaded at all.

Also fixed on the way: connections created after startup had no metastore catalog
entry, because catalogs are derived from the registry at boot only.

PR-1 first: it is the only item where the product misbehaves. PR-3 can land in parallel — it
touches no code. PR-2 carries D1 and deserves its own review.

## 5. Acceptance checks

Re-run on a clean container; each maps to a claim this plan corrects.

1. `uv sync` → `/investigations/{id}/export` returns **501** naming the extra. No 500, no traceback.
2. `import aughor.export` succeeds with `EXPORT_AVAILABLE is False` when the extra is absent.
3. First `uv run aughor up` on a fresh clone prints the full boot summary — no 30 s timeout line.
4. With no model configured the summary reads `not ready (no model configured)`, not `ready`.
5. No `data/*.duckdb` exists after a first boot; the demo connection is absent until `aughor seed`,
   and after seeding it appears and opens. Seeding completes in **< 5 s**.
6. `git status` is clean after `uv sync --all-extras` and `npm install`.
7. `uv run pytest -q -m "not e2e and not eval"` is fully green offline (two named skips allowed).
8. README's stated sizes, test count and Node floor match a fresh measurement.

## Appendix — measurements

| Measurement | Value |
|---|---|
| `uv sync --all-extras` | exit 0, 194 packages, **1.2 GB** venv |
| `uv sync` (serving core) | exit 0, 106 packages removed, **362 MB** venv |
| `npm install` (auto, first run) | 885 packages, 26 s |
| `ensure_fixture_db` (blocks startup) | **98.2 s** → 2.1 MB, 72,000 rows |
| `ensure_samples_db` | 0.1 s → 1.6 MB |
| 72k-row insert: `executemany` vs chunked `VALUES` | **45.7 s → 1.7 s** |
| Backend suite | 7,024 passed · 32 skipped · 2 failed (W6) · **11 m 49 s** serial, 4 cores |
| Frontend build | 13.9 s |
| `ruff` / `tsc --noEmit` / 3 lint gates / `gen:api` | all clean |
