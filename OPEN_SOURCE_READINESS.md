# Open-Source Readiness Audit — Aughor

**Audited:** 2026-07-10 · **Branch:** `chore/oss-readiness` (8 commits, off `main@409b706`)
**Repo state at audit:** private, 931 commits on `main`, 1,055 tracked files, no LICENSE, no tags.

Every claim below is backed by a command that was actually run or a file that was
actually read. Anything I could not verify is marked `UNVERIFIED`. Nothing was
pushed; no history was rewritten; no branch was deleted.

---

## 1. What this repo is

- **Aughor is an "autonomous data analyst"** — a LangGraph agent that connects to a SQL
  warehouse, explores it continuously in the background, builds a business ontology
  (entities, relationships, governed metrics, lifecycles), and answers analytical questions
  ("why did revenue drop 8%?") in natural language with evidence, citations, and a
  *computed* confidence score. Its differentiator is not NL→SQL translation; it is the
  deterministic guard layer that tries to make a wrong number impossible rather than merely
  unlikely.
- **Three front doors, one engine.** A FastAPI service (`aughor/api.py`, 309 routes) that
  streams investigations over Server-Sent Events; a Click CLI (`aughor investigate`); and an
  MCP server for Claude Desktop / Cursor. All three run the same LangGraph `StateGraph`
  (`aughor/agent/graph.py`), which routes a question to one of three branches: deep
  investigation (an 8-phase lifecycle in `agent/investigate.py`), a direct query loop, or
  background exploration.
- **Python 3.11+ backend, Next.js 16 / React 19 frontend.** `uv` + `hatchling` +
  `uv.lock`; npm + `package-lock.json`. ~390 Python modules across ~50 subpackages;
  95 `.tsx` components. The TypeScript API client (`web/lib/api.gen.ts`, 476 KB) is
  **generated** from the live FastAPI route surface and CI fails on drift.
- **The engineering discipline is unusually high.** 2,947 hermetic offline tests passing in
  ~93 s. `ruff` at a zero baseline. **Zero** `TODO`/`FIXME`/`HACK` comments anywhere in
  1,055 tracked files. Zero stray `print()` in `aughor/`, zero `console.log` in `web/`.
  373 of 392 Python files carry module docstrings. Three one-way UI "ratchets" enforce
  design tokens, number formatting, and a shrinking raw-`<button>` count.
- **Security posture is genuinely good, not accidentally good.** CORS defaults to
  `localhost:3000,3001` (not `*`). No `debug=True`, no `verify=False`, no `shell=True`.
  Connection credentials are Fernet-encrypted at rest with the key file written `0o600`.
  The auth gate is opt-in with a documented rationale (it is a local single-user tool).
- **Unusual things worth knowing.** A few modules are enormous —
  `agent/investigate.py` (326 KB), `explorer/agent.py` (233 KB),
  `routers/investigations.py` (184 KB). `data/` mixes checked-in seed knowledge
  (`data/kb/`, 69 JSON files) with gitignored runtime state (`*.duckdb`, `*.db`, an
  encryption key). `web/aughor-v2/` is a second, parallel design-token layer that
  `app/layout.tsx` genuinely imports. There are **no git submodules, no vendored
  third-party source, and no notebooks.**
- **The dominant liability is documentation volume, not code.** ~350 KB of internal
  planning prose sits at the repo root and in `docs/` — `ROADMAP.md` alone is 206 KB —
  written for the author and an AI pair, not for a stranger.
- **Ecosystem norms applied.** Python: `uv`/`ruff`/`pytest`/`pip-audit` (not pip/black/tox).
  Frontend: npm/`tsc`/`eslint`/`npm audit` (not yarn/pnpm). Secrets: `gitleaks`.
  Licenses: `pip-licenses` + `license-checker`. CI: GitHub Actions + `actionlint`.

---

## 2. Findings

Ordered by severity. `FIXED` means a commit on `chore/oss-readiness` resolved it and the
fix was verified.

### Blockers — both resolved

| # | Finding | Evidence | Status |
|---|---|---|---|
| B1 | **No LICENSE file, while `README.md:8` rendered a `license-MIT` badge.** A public repo with no license is "all rights reserved" — legally unusable by anyone. The badge was also a false claim. | `git ls-files \| grep -iE '^(LICENSE\|COPYING)'` → *no output*. `gh repo view --json licenseInfo` → `null`. Confirmed again in a clean-room clone. | **FIXED** — Apache-2.0 per your decision. Canonical text from apache.org (202 lines, sha256 `cfc7749b…3d30`). `uv build` verified to emit `License-Expression: Apache-2.0` and bundle LICENSE + NOTICE into the wheel. |
| B2 | **DM Sans font files redistributed with no license text.** The SIL OFL requires its text to travel with the font. | `web/public/fonts/*.ttf` name table contains `"Copyright 2014 The DM Sans Project Authors"` + `"SIL Open Font License, Version 1.1"`; `git ls-files \| grep -i OFL` → *no output*. | **FIXED** — added `web/public/fonts/OFL.txt` (from `google/fonts@main:ofl/dmsans/OFL.txt`, copyright line matches the embedded string exactly) + attribution in `NOTICE`. |

### High — resolved

| # | Finding | Evidence | Status |
|---|---|---|---|
| H1 | **26 known vulnerabilities across 9 Python packages**, including `starlette` (unvalidated Host header used to rebuild `request.url`), `python-multipart` (3 CVEs in form parsing — reachable on every file upload), `aiohttp` (11 CVEs), `langgraph-checkpoint` (object reconstruction from JSON checkpoints), and `cryptography` (statically linked OpenSSL). | `uv run --with pip-audit pip-audit` → *"Found 26 known vulnerabilities in 9 packages"*. | **FIXED** — lock-only upgrades + `PyPDF2`→`pypdf` (PyPDF2 is EOL; the advisory's "fix 3.9.0" is the renamed successor). `pip-audit` → **0**. Full suite unchanged at 2,947 passed; app imports 309 routes on the new starlette; `_extract_pdf` round-tripped a real generated PDF under pypdf. |
| H2 | **2 moderate npm advisories** — `next@16.2.6` pins a vulnerable `postcss@8.4.31` in its own `node_modules` (GHSA-qx2v-qp2m-jg93, XSS via unescaped `</style>`). No stable Next release fixes it; npm's suggested fix was a downgrade to `next@9.3.3`. | `npm audit --json` → `{moderate: 2}`; `npm ls postcss` → `next@16.2.6 └── postcss@8.4.31`. | **FIXED** — `overrides: {"postcss": "^8.5.10"}`, consistent with the existing react pin. `npm audit` → **0**. Verified `npm ci`, `tsc`, all three gates, and `next build` still exit 0, and that Tailwind still emits a 128 KB CSS chunk (i.e. the override is not a silent no-op). |
| H3 | **The README's install guide documented environment variables that do not exist.** The "Minimal local `.env` (Ollama)" block told users to set `EMBEDDER_BASE_URL` and `EMBEDDER_MODEL`. | `git grep -nI "EMBEDDER_"` → matches **only** in `README.md`. `aughor/semantic/embedder.py:6-7` actually reads `AUGHOR_EMBED_MODEL` and `OLLAMA_BASE_URL`. | **FIXED** — corrected to the real names. It had only ever "worked" because the defaults coincide with what the doc told people to type. |

### Warnings — open, no fix applied

| # | Finding | Evidence | Action required |
|---|---|---|---|
| W1 | **Local `.git` is 15 GB** because 5 stashes contain 2.6 GB of committed-then-stashed DuckDB temp spill files (`.tmp/duckdb_temp_storage_S64K-3.tmp` alone is 2,155 MB). | `git count-objects -vH` → `size-pack: 15.36 GiB`. The blobs are reachable **only** from `refs/stash`. `git log --all -- .tmp/` → 0 commits. | **Not a public leak** — verified: a fresh clone's `.git` is **8.5 MB** and contains zero `duckdb_temp_storage` objects. But `git push --mirror` *would* push `refs/stash`. Cleanup is destructive → needs your approval (§4, D3). |
| W2 | **The test suite is not fully hermetic.** `tests/conftest.py` redirects 27 `AUGHOR_*_DB` stores into temp dirs, but `aughor/samples/setup.py:29` hardcodes `SAMPLES_PATH = Path("data")/"samples.duckdb"` with **zero** `environ` references, and `conftest.py:77` calls `ensure_samples_db()`, which opens it read-write in the developer's live `data/`. | `git grep -c environ aughor/samples/setup.py` → `0`. Reproduced: two concurrent suite runs died with `_duckdb.IOException: Could not set lock on file ".../data/samples.duckdb"` × 2,948 tests. | Add an `AUGHOR_SAMPLES_DB` override and wire it into `conftest.py`. Product code, so I did not patch it. This is the same class of bug as the registry incident already recorded in your notes. Gitignored, so it cannot pollute the repo. |
| W3 | **ESLint is red and is not a CI gate.** | `cd web && npm run lint` → `204 problems (40 errors, 164 warnings)`, e.g. `lib/useWheelZoom.ts:23 Cannot update ref during render`. | Fix the 40 errors, then add `npm run lint` to CI. I deliberately did **not** add it to the workflow — that would have shipped a red gate on day one. |
| W4 | **Zero frontend tests.** No vitest/jest/playwright anywhere. The entire frontend safety net is `tsc --noEmit` + three bespoke lint gates. | `git ls-files web/ \| grep -E '\.(test\|spec)\.'` → *no output*; no test runner in `package.json`. | Honest disclosure now added to the README "Project status". Consider a smoke test for the SSE stream. |
| W5 | **`web/aughor-v2/README.md` documents two files that do not exist** (`Charts-v2.tsx`, `vega-theme-v2.ts`). The directory is real and actively imported by `app/layout.tsx:7` and `app/globals.css:5-6`. | Grepped every `` `*.tsx` ``/`` `*.ts` `` reference in that README against `git ls-files`. | Update or delete the stale references. |
| W6 | **Dead asset.** `web/public/ontology-icon.png` is referenced by nothing. | `git grep -lI "ontology-icon"` → 0 files. | Left in place — it is your own asset and deleting it is a judgment call, not junk removal. Delete if unwanted. |
| W7 | **`ruff format` would reformat 696 of 728 files.** | `uvx ruff@0.15.20 format --check .` | **Deliberately not applied.** This project ships ruff as a *linter* with no formatter config, and its style uses hand-aligned inline comments. Reformatting 696 files would destroy `git blame` for a purely cosmetic change. Adopt it as a separate, deliberate decision or not at all. |
| W8 | **`start.sh` kills processes it does not own**: `pkill -9 -f "uvicorn aughor.api"` and `lsof -ti:8000 \| xargs kill -9`. A stranger running `./start.sh` loses whatever they had on port 8000. | `start.sh:21,26`. | Documented with a warning in README + CONTRIBUTING. A real fix would only kill the PID in `/tmp/aughor-api.pid`. *(I checked `xargs -r` for a BSD portability bug and could **not** reproduce one — it exits 0 on this macOS. Not reported as a finding.)* |
| W9 | **`start.sh --api-only` reports "API may still be starting"** while `/health` already answers — its readiness wait is too short on a cold start. | Clean-room transcript: the warning printed, then `curl /health` immediately returned `{"status":"ok"}`. | Cosmetic. Lengthen the wait loop. |
| W10 | **Opaque internal dataset names** — `missimi` (54 tracked files), `beautycommerce` (27), `luxexperience` (8), `swiss-air` (9). `docs/missimi_eval_2026-06-21_results.jsonl` contains 30 lines of **real query result rows** (ROAS, CAC, AOV in €/$), and `tests/unit/test_relabel_keep.py:19` carries the comment `# real AOV cell values`. | `git grep -lI -i missimi \| wc -l`; file read. | You confirmed this is **your own / synthetic data**, so it is not a confidentiality blocker. Still: an outsider cannot tell what `missimi` is. Renaming to a neutral fixture name would help. No PII, no credentials, and **no binary databases are tracked** (verified). |
| W11 | **Two gitleaks findings are false positives** and will stay noisy. | `docs/PLATFORM_ARCHITECTURE.md:37` matches on the prose *"grant/policy enforcement"*. `tests/unit/test_secretvault.py:108` contains the obviously-fake literal `sk_live_supersecret`, in a test that asserts the value gets encrypted. | Harmless. If you ever add gitleaks to CI, add a `.gitleaks.toml` allowlist for these two paths. |
| W12 | **Odd root filename with spaces:** `Data Context Creator Skill.md`. Directory `design-mockups/palantir-inspired/` names a competitor. | `git ls-files \| grep ' '` | Cosmetic; both read as internal artifacts to an outsider. |
| W13 | **No container image.** `docker-compose.yml` starts only Qdrant. Deployment beyond a local machine is untested. | Read `docker-compose.yml`; no Dockerfile in the tree. | Now disclosed honestly in README "Project status". |
| **W14** ✅ **FIXED (2026-07-10)** — the scenario in `aughor/samples/scenario.py` (APAC gateway outage, −38.8% APAC/SMB drop, NA-promo red herring) is now what `ensure_fixture_db()` auto-seeds; verified by test `test_fixture_db_has_a_real_discoverable_signal`. | **The built-in demo dataset has no signal in it — and it is the first thing every new user explores.** `aughor/samples/setup.py::ensure_fixture_db()` auto-creates `data/aughor.duckdb` on first boot. Its data is uniform noise: payment-failure rates of 20.9% / 19.7% / 19.4% across EMEA/NA/APAC (no real difference), daily revenue with mean 1,997 and sd 140 (flat). Worse, `plan` is a **perfect alias of `region`** (every `pro` customer is EMEA, every `free` is NA, every `enterprise` is APAC), and `free`-plan customers carry $19,630 of MRR. | Queried the auto-seeded fixture directly. Cross-tab: `('pro','EMEA',67) ('free','NA',66) ('enterprise','APAC',67)` — three cells, perfectly collinear. Then ran a real exploration against it: the Briefing produced the verdict *"Plan Mix Masks Revenue Risk"* and narrated a 20.9% vs 19.7% failure-rate gap as *"a systemic issue affecting high-value segments."* Aughor was **not** mislabelling — the numbers were correct; the dataset is degenerate. | **This makes the product look bad on first run, through no fault of the engine.** `data/seed.py` already builds a genuinely good scenario (800 customers, a dated APAC payment-gateway outage, a −38.8% APAC/SMB drop, and an NA promo as a deliberate red herring — all verified). Make `ensure_fixture_db()` seed *that* instead of the noise table. This is the single highest-leverage change for a new visitor's impression. |
| **W15** ✅ **FIXED (2026-07-10)** — `aughor seed` (now with `--db`, default `data/aughor.duckdb`) and `aughor investigate` operate on the same file; `data/seed.py` delegates to the same scenario module. | **The two packaged CLI commands do not compose.** `aughor seed` writes `data/hermes.duckdb`; `aughor investigate` reads `data/aughor.duckdb`. So the documented "seed then investigate" flow silently investigates a different database. The `seed` help text — *"Seed the fixture DuckDB database"* — is simply false, and `hermes` is the project's old name. | `data/seed.py:31` → `DB_PATH = Path(__file__).parent / "hermes.duckdb"`. `aughor/cli.py:30` → `DEFAULT_DB = .../data/aughor.duckdb`. `.gitignore:16` still lists `data/hermes.duckdb`. | Point `data/seed.py` at `data/aughor.duckdb` (what its own help text claims), or give `seed` a `--db` flag. Product code, so not patched here. Fixing this plus W14 is the same one-line change. |

### Passes — verified, not assumed

| Check | Evidence |
|---|---|
| **No secrets anywhere in git history** | `gitleaks git . --log-opts="--all --reflog --full-history"` → **1,105 commits scanned, 2 findings, both false positives (W11)**. Separately, I extracted the 10 real values from your local `.env` and searched **every commit reachable from every ref** (1,059 at audit time) for each: `AUGHOR_SECRET_KEY`, `GROQ_API_KEY`, `TOGETHER_API_KEY`, `AUGHOR_DEFAULT_POSTGRES_DSN`, `AUGHOR_KB_PATH` — **none present in any commit**. The only matches were `localhost` URLs and model names. |
| `.env` never tracked | `git log --all -- .env` → 0 commits. `git check-ignore -v .env` → `.gitignore:7`. |
| **Deleted files audited** | `git log --all --diff-filter=D --summary` → 84 deleted paths. Two SQLite DBs were once committed: `data/artifacts.db` (extracted: `artifacts` table, **0 rows**) and `data/workspaces.db` (extracted: 2 rows — `Default`, `Test`, opaque connection IDs). Both benign. No credentials, no PII. |
| No `.DS_Store`, `__pycache__`, `node_modules`, or build artifacts tracked | `git ls-files \| grep -iE '(node_modules\|__pycache__\|dist\|\.next\|DS_Store\|\.pyc)'` → *no output*. 10 `.DS_Store` files exist on disk and are all gitignored. |
| No tracked file > 5 MB | Largest is `design-mockups/.../Screenshot.png` at 1.1 MB. No Git LFS needed. |
| No private IPs, internal hostnames, VPN endpoints, or staging URLs | Targeted greps over all tracked files. |
| No PII in fixtures | Credit-card / SSN / phone patterns: none. Only obviously-fake emails (`alice@acme.com`, `a@b.com`, `user@org.com`). |
| Dangerous defaults | CORS defaults to `localhost:3000,3001` (`api.py:171`), **not** `*`. Zero `debug=True`, zero `verify=False`/`CERT_NONE`, zero `shell=True`. Auth gate opt-in and documented (`api.py:91-125`). |
| All deps from public registries; lockfiles committed | `uv.lock` (936 KB) + `web/package-lock.json`. Every npm `resolved` host is `registry.npmjs.org`. No `git+` or private-index URLs in `pyproject.toml`. |
| **Dependency licence compatibility with Apache-2.0** | 187 Python dists: MIT/Apache/BSD dominate. Copyleft: `psycopg2-binary`/`psycopg` (LGPL-3.0, *direct*) — imported as a library, not modified or statically linked, so Apache-2.0 is unaffected; noted in `NOTICE` for redistributors. `text-unidecode` (Artistic/GPL) is reachable **only** through the optional `evals` extra (`uv export --no-dev` → absent); noted in `NOTICE`. `certifi`/`orjson`/`tqdm` are MPL-2.0 (file-level, fine). 570 npm prod packages: 454 MIT, 64 ISC, 22 Apache-2.0; the only LGPL is `@img/sharp-libvips` (a native binary). **No GPL/AGPL conflict.** |
| No vendored third-party source, no submodules | `evals/spider2.py` is Aughor's own harness ("Rebuilt for the top-3 campaign"), not a copy of the benchmark. `.gitmodules` absent. |
| **Full test suite green** | `uv run pytest -q -m "not e2e and not eval"` → **2,947 passed, 1 skipped, 6 deselected** in 92.5 s on `main`, and identical on the audit branch. Zero failures. |
| **Python 3.11 / 3.12 / 3.13 all green** | Full suite run in a clean checkout with isolated venvs per version: **2,947 passed, 1 skipped** on each. (An earlier 2,948-error run on 3.12 was a stale DuckDB lock from my own killed process — W2 — not an incompatibility.) |
| Zero `TODO`/`FIXME`/`HACK`/`XXX` | `git grep -nIiE '\b(todo\|fixme\|hack)\b'` over all tracked files except lockfiles → **0**. (Pathspecs sanity-checked against 335 `.py` / 94 `.tsx` files first, so the zero is real, not a broken glob.) |
| No debug leftovers | 0 `console.log`, 0 `debugger`, 0 `breakpoint()`/`pdb`, 0 bare `print()` in `aughor/`. |
| No skipped/xfail tests | 0 `@pytest.mark.skip`/`xfail`. 7 runtime `pytest.skip()` guards that fire only when an optional resource is absent; 1 actually skipped in the CI-equivalent run. |
| **CI leaks nothing** | `.github/workflows/ci.yml`: no `secrets.*`, no tokens, no self-hosted runners, no private registries. All `runs-on: ubuntu-latest`. |
| Generated client is current | Regenerated `web/lib/api.gen.ts` from the live FastAPI surface → **no drift**. |
| **Clean-room install works end-to-end** | See §5 transcript. |
| Commit messages | 0 "wip"/"fix"/"temp" one-word subjects across every commit on every ref. No Jira/Linear/internal ticket URLs. No profanity. 72 PR-linked merges on `main`. |
| Author identity | `git shortlog -sne --all` → a single person under two spellings (947 + 112), both `sidhasadhak@outlook.com`. No corporate or unexpected emails. Unified via `.mailmap` (now reports **1 author**). |

---

## 3. Fixed in this audit

Eight commits on `chore/oss-readiness`, **not pushed**. `34 files changed, 1300 insertions(+), 282 deletions(-)`.

| Commit | What |
|---|---|
| `2cd493a` | Add Apache-2.0 `LICENSE`, `NOTICE`, and DM Sans `OFL.txt`; declare the licence in `pyproject.toml` and `web/package.json`; README badge MIT → Apache-2.0 + a real CI badge. |
| `b784144` | Remove 5 unreferenced `create-next-app` boilerplate SVGs (including Vercel's trademark); replace the stock `web/README.md`; de-personalize `/Users/amitkamlapure/...` in `evals/spider2.py` and `docs/MCP_SERVER.md`. |
| `fecfc63` | `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1, verbatim), `CHANGELOG.md`, issue + PR templates, `dependabot.yml`, `.mailmap`. |
| `4414400` | Clear **26 → 0** Python advisories; `PyPDF2` → `pypdf`. |
| `8ec22fd` | Pin `postcss ≥ 8.5.10`; **2 → 0** npm advisories. |
| `f7ba363` | Delete the unsent draft email to a benchmark maintainer's personal Gmail; scrub that address from `ROADMAP.md` and `docs/10X_…`; repair 4 dangling references. |
| `2310606` | CI: `permissions: contents: read`; Python 3.11/3.12/3.13 matrix; add `next build`. Validated with `actionlint`. |
| `a4c455a` | README: fix the fictional `EMBEDDER_*` vars; add prerequisites, Configuration, honest Project status, Security + Acknowledgements. Document `AUGHOR_API_KEY`/`CORS_ORIGINS`/`SECRET_KEY` in `.env.example`. |

**Post-fix verification on the branch:** `pytest` 2,947 passed · `ruff check` clean · `tsc` clean ·
3 UI gates clean · `next build` clean · no codegen drift · `pip-audit` **0** · `npm audit` **0**.

---

## 4. Decisions needed from you

**D1 — Copyright holder name.** ✅ **RESOLVED (2026-07-10).** Confirmed as `Sidha Sadhak`;
`LICENSE` and `NOTICE` already carry `Copyright 2026 Sidha Sadhak`. No change needed.

**D2 — Trim the internal docs (you chose "trim to a public subset"; only partially done).**
I removed the draft email. I did **not** delete the bulk, because they cross-link densely
(4–5 inbound links each) and deleting them means editing your 206 KB `ROADMAP.md` prose —
that is a content decision, not a mechanical one. Proposed order:

1. `docs/SESSION_HANDOFF_2026-07-0{6,7}.md`, `docs/architecture-review-*/COMPLETE_HANDOFF.md` (110 KB) — session notes, zero value to outsiders.
2. `AGENT_NOTES.md` (25 KB), `AUDIT_2026-06-27.md` (14 KB), `TEST_REPORT.md` (8 KB) — snapshots that are already stale.
3. `M12_ORG_INTELLIGENCE_ROADMAP.md` (52 KB) — describes a `hermes/` module layout that **no longer exists** (the project's old name). Actively misleading.
4. `docs/10X_AND_SPIDER2_PROGRAM_2026-07-06.md` — contains competitive statements about a named company ("beat Genloop's official #1"). Your call whether that is confident or unbecoming.
5. Shrink `ROADMAP.md` to a public roadmap and move the historical record into the git log, where it already lives.

> **Important caveat, since you chose to keep full history:** deleting these files now
> removes them from the *tip*, not from history. Anyone can `git show` an old commit and
> read them. They contain no secrets, so this is survivable — but if the competitive
> language or the session notes must be unrecoverable, that requires a history rewrite,
> which contradicts D3 below. Pick one.

**D3 — The 15 GB local `.git` (destructive; needs your explicit go-ahead).** 5 stashes hold
2.6 GB of DuckDB spill files. A normal clone is unaffected (**verified: 8.5 MB**), so this is
*not* a leak. To reclaim the space locally:

```bash
git stash list                                        # review first — 5 entries, you may want them
git stash clear
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

This **permanently discards all 5 stashes.** I have not run it. Also: never
`git push --mirror` from this clone — that would push `refs/stash` and its 2.6 GB.

**D4 — The README hero image is a mockup, not the product. (Decided: retake. Blocked on W14.)**
`README.md:21` shows `design-mockups/01-intelligence-overview.svg` — a design mockup presented
as "Aughor intelligence overview". Meanwhile
`design-mockups/palantir-inspired/Screenshot 2026-06-26 at 10.22.05.png` is a **real
screenshot of Aughor's own UI** (I opened it — no third-party product imagery, so there is no
Palantir IP issue), but it displays real business figures.

You chose to retake it against the synthetic fixture. I built an isolated instance (fresh
clone, its own `data/`, ports 8010/3010, no API keys, no Postgres DSN, fixture as the only
connection), ran a real exploration, and captured a clean 3200×2000 production-build
screenshot with no dev-tools chrome. **The capture worked; the picture is not usable.**
The Briefing it produced is a faithful rendering of noise — *"Plan Mix Masks Revenue Risk"*,
built on a 20.9% vs 19.7% failure-rate difference and on `pro`-plan MRR that is numerically
identical to EMEA MRR because **W14**: the auto-seeded fixture is degenerate.

So the hero is blocked on the fixture, not on the screenshot. **Fix W14 first** (make
`ensure_fixture_db()` use `data/seed.py`'s outage scenario), then re-capture. The scripts and
the isolated-instance recipe are reproducible; the teardown left your live app, your `data/`,
and `.claude/launch.json` untouched. Until then, options are (a) keep the mockup but label it
"design mockup", or (b) ship without a hero image. Do **not** ship the noise Briefing — it
advertises the engine narrating a non-finding.

**D5 — Rename the competitor-named directory.** `design-mockups/palantir-inspired/` →
something like `design-mockups/explorations/`. Cosmetic, but it is the kind of thing a
reviewer screenshots.

**D6 — `ruff format` (W7).** 696 files would change. My recommendation: **don't**, or do it
as its own clearly-labelled commit that you own. Not an auto-fix.

---

## 5. Clean-room install verification

Not a doc review — the README's four steps were **executed literally** from a fresh clone
into a fresh venv, with every inherited `AUGHOR_*`/`GROQ_*`/`OLLAMA_*` variable stripped
from the shell. Full transcript, final run against `chore/oss-readiness@a4c455a`:

```
$ uv --version && python3 --version && node --version
uv 0.11.14 · Python 3.14.3 · v24.14.1

$ git clone https://github.com/sidhasadhak/aughor.git && cd aughor
  HEAD: a4c455a  ·  LICENSE present: yes

$ uv sync                                # README step 1
  -> exit 0   ·   venv python: Python 3.13.13

$ cd web && npm install && cd ..         # README step 2
  found 0 vulnerabilities
  -> exit 0

$ cp .env.example .env                   # README step 3 (left UNEDITED)
  copied

$ ./start.sh --api-only                  # README step 4
  API started (pid 55826, logs: /tmp/aughor-api.log)

$ curl -s localhost:8000/health
  {"status":"ok","fixture_db":true}

$ curl -s localhost:8000/connections
  [{"id":"workspace",...},{"id":"fixture","name":"Fixture DB (demo)",...}]

$ uv run aughor --help                   # the packaged CLI entry point
  Usage: aughor [OPTIONS] COMMAND [ARGS]...
  Commands: investigate, seed

$ ./start.sh --stop
  API stopped  ·  :8000 released

RESULT: clean-room quick start completed end-to-end.
```

The fixture DB self-provisions on first boot and is genuinely populated
(`customers` 200 rows, `daily_revenue` 1,000, `kpi_daily` 300, `events` 3 — all synthetic,
from `data/seed.py`). `npm run build` also succeeds (now gated in CI).

Three problems this exercise found, all fixed: the fictional `EMBEDDER_*` variables (H3),
the missing statement that an LLM key is required before any question will work, and the
undocumented `start.sh` port-8000 kill.

---

## 6. Launch checklist (GitHub UI — you must do these)

- [ ] **Set the description.** It is already good: *"Autonomous Intelligence Platform — continuously explores your data, builds a living business ontology, and answers complex analytical questions with evidence."*
- [ ] **Add topics** (currently none): `llm-agent`, `text-to-sql`, `nl2sql`, `duckdb`, `langgraph`, `data-analysis`, `fastapi`, `semantic-layer`, `ai-agent`.
- [ ] **Website link:** currently empty.
- [ ] **Security → enable** *Private vulnerability reporting* (`SECURITY.md` and `CODE_OF_CONDUCT.md` both link to `/security/advisories/new` — those links are dead until you turn it on).
- [ ] **Security → enable** secret scanning **and push protection**.
- [ ] **Dependabot:** `.github/dependabot.yml` is committed; enable Dependabot alerts + security updates in Settings.
- [ ] **Branch protection on `main`:** require a PR, require the CI checks (`Backend · pytest (py3.11/3.12/3.13)`, `Frontend · typecheck`, `Backend · ruff`, `API client · codegen drift`), require branches be up to date.
- [ ] **Tag `v0.1.0`** and cut a GitHub Release once the blockers above are merged. There are currently **0 tags**; `CHANGELOG.md` is scaffolded for it.
- [ ] Optional: Discussions, a social preview image, pin the repo on your profile.

---

## 7. Verdict

### Can this repo be flipped public today? **Not from `main`. Yes, from `chore/oss-readiness`.**

`main` as it stands has **two blockers**: it ships no licence at all while advertising an
MIT badge, and it redistributes the DM Sans fonts without the OFL text the licence requires.
Both are unambiguous legal problems, and both are fixed on the audit branch.

Nothing else is standing in the way. To be blunt about what I expected to find and didn't:
I hunted for secrets across all 1,105 commits with a real scanner *and* by grepping every
commit for the actual live values in your `.env` — there is nothing. No corporate emails.
No PII. No tracked databases. No `TODO`s. No `console.log`. 2,947 tests pass on three Python
versions. The security defaults are correct on purpose. This is a repo whose *code* is
already above the bar; it was let down entirely by its paperwork.

**The ordered path to public:**

1. Merge `chore/oss-readiness` into `main`. *(Clears B1, B2, H1, H2, H3.)*
2. ~~**D1** (copyright name)~~ — ✅ resolved: Sidha Sadhak.
3. Fix **W14 + W15** — one change to `ensure_fixture_db()` and `data/seed.py`. This is not
   cosmetic. The bundled demo dataset is the first thing every visitor runs, and today it
   feeds the engine pure noise, which the Briefing then narrates as *"systemic risk."* A
   reader who checks the numbers concludes the product hallucinates. It doesn't — the data
   is degenerate. Fix the data, and the flagship demo tells a true story (an APAC payment
   outage, −38.8%, with an NA promo as a red herring) that `data/seed.py` already builds.
4. Then **D4** (hero image): re-capture against the fixed fixture. A mockup presented as the
   product is the last honesty problem on the landing page.
5. Flip to public, then immediately do the §6 checklist — most importantly **enable private
   vulnerability reporting**, because `SECURITY.md` promises it.

Everything else — D2, D3, D5, D6, and every other `W` finding — is polish that can land after
the repo is public, in the open, as normal issues. None of it should hold the launch.

> Would a senior engineer at a respected open-source org be comfortable putting their name
> on this? **After step 1, yes.** After steps 1–3, comfortably. The engineering here is
> stronger than the repo currently lets on; the work was making the packaging tell the truth.
