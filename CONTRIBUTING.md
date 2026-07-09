# Contributing to Aughor

Aughor is in active alpha. Issues, ideas, and pull requests are all welcome.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
Contributions are accepted under the [Apache License 2.0](LICENSE).

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | latest | Python dependency + venv manager. The lockfile is `uv.lock`. |
| Python | 3.11+ | `requires-python = ">=3.11"`. CI pins **3.11**. |
| Node.js | 20 | CI pins **20**. The frontend uses npm and `web/package-lock.json`. |

An LLM backend is only needed to *run* Aughor, not to develop against it — the
test suite is fully offline and hermetic.

## Setup

```bash
git clone https://github.com/sidhasadhak/aughor.git
cd aughor

uv sync                       # backend deps into .venv
cd web && npm install && cd ..  # frontend deps

cp .env.example .env          # then edit: pick an LLM backend and set its key
./start.sh                    # API on :8000, web on :3000
```

`./start.sh` also accepts `--api-only`, `--web-only`, and `--stop`.

> **Heads-up:** `start.sh` frees port 8000 before starting, which will kill any
> unrelated process listening there.

On first boot Aughor provisions a synthetic DuckDB fixture (`data/aughor.duckdb`)
so you have something to query immediately. No real data required.

## Running the checks

CI runs exactly these four jobs. Run them locally before opening a PR:

```bash
# 1. Backend tests — hermetic, no network, no LLM. ~90s.
uv run pytest -q -m "not e2e and not eval"

# 2. Backend lint — the baseline is zero.
uvx ruff@0.15.20 check .

# 3. Frontend typecheck + the three UI gates
cd web
npx tsc --noEmit
npm run lint:tokens     # no raw border-radius / pixel font-size
npm run lint:format     # numbers and dates go through lib/format.ts
npm run lint:elements   # one-way ratchet: raw <button> count may only shrink

# 4. Generated API client must not drift
npm run gen:api && git diff --exit-code -- lib/api.gen.ts
```

### Test markers

| Marker | What it does | In CI? |
|---|---|---|
| *(none)* | Fast, hermetic unit + integration tests | ✅ |
| `e2e` | Hits a live LLM; ~100s per test | ❌ (`--run-e2e` to opt in) |
| `eval` | Accuracy / token-cost ratchet against a real warehouse | ❌ |

`tests/conftest.py` redirects every datastore to a temp directory before the app
is imported, so the suite can never touch `data/`. If you add a new persistent
store, wire its `AUGHOR_*_DB` env override into that fixture — a store that
ignores its override will silently corrupt a contributor's real data.

## Project conventions

These are load-bearing; a PR that ignores them will get review comments.

- **Build → wire → test → leverage.** A feature isn't done when the module
  exists. It is done when it runs on the real path and a test proves it fires.
- **Every guard ships with a test that proves it fires.** Not a test that the
  function exists — a test that the guard actually catches the thing it exists
  to catch.
- **Never raise a ratchet baseline.** `ruff` is at zero, and the frontend
  raw-element count only shrinks. If a change needs a new suppression, say why
  in the PR.
- **New behaviour lands behind a flag, default-off.** See `aughor/kernel/flags.py`.
  The default install should be byte-identical before and after your change.
- **Don't swallow exceptions silently.** Use `aughor.kernel.errors.tolerate` so
  a degraded path is counted rather than invisible.

## Pull requests

1. Branch off `main`.
2. Keep the change focused. A PR that fixes a bug *and* refactors a subsystem
   is two PRs.
3. Write a description that states what changed and how you verified it. If you
   ran it against a live warehouse, say so and say what you saw.
4. All four CI jobs must be green.

## Reporting bugs

Open an issue with the reproduction, what you expected, and what happened. If it
involves a wrong *number*, include the question you asked and the SQL Aughor
generated — both are in the Trust Receipt on the answer.

For security vulnerabilities, do **not** open an issue — see [SECURITY.md](SECURITY.md).
