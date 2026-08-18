# Contributing to Aughor

Aughor is in active alpha. Issues, ideas, and pull requests are all welcome.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
Contributions are accepted under the [Apache License 2.0](LICENSE).

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | latest | Python dependency + venv manager. The lockfile is `uv.lock`. |
| Python | 3.11+ | `requires-python = ">=3.11"`. CI pins **3.11**. |
| Node.js | 20.9+ | `next@16` requires `>=20.9.0`. CI pins **20** (latest 20.x). The frontend uses npm and `web/package-lock.json`. |

An LLM backend is only needed to *run* Aughor, not to develop against it — the
test suite is offline and hermetic, bar two tests that fetch a DuckDB extension
(see **Running the checks**).

## Setup

```bash
git clone https://github.com/sidhasadhak/aughor.git
cd aughor

uv sync --all-extras          # backend deps into .venv
cd web && npm install && cd ..  # frontend deps

cp .env.example .env          # then edit: pick an LLM backend and set its key
./start.sh                    # API on :8000, web on :3000
```

`./start.sh` also accepts `--api-only`, `--web-only`, and `--stop`.

> **Use `--all-extras` for development.** A bare `uv sync` installs the serving core only
> (a ~350 MB venv rather than ~1.2 GB, for size-limited deployments) and omits report export,
> semantic search and the fast bulk reader. Nothing crashes without them — each degrades
> with a message naming the extra — but tests that exercise those paths will skip, and you
> will wonder why a PDF export returns 501. See **Optional extras** in the README.

> **Note:** the `npm install` step above is optional — `./start.sh` (a thin alias
> for `uv run aughor up`, the [README Quick Start](README.md#quick-start) path)
> installs frontend deps on first run. It never kills a busy port's owner: if
> `:8000`/`:3000` is already taken it reports who holds the port and exits, so
> free it yourself or pick another with `--api-port` / `--web-port`.

Nothing is seeded on boot. Run `uv run aughor seed` to write the synthetic DuckDB
fixture (`data/aughor.duckdb`) when you want something to query without connecting
real data — it takes a couple of seconds and then shows up as a connection. The test
suite seeds its own copy in a temp dir, so it never needs this.

> **Most of `data/` is gitignored, but four paths are deliberately not:**
> `data/context_graph/` (the Wave-C connection knowledge graph),
> `data/ontology_overrides/` (the human override overlay),
> `data/ontology_docs/` (the R8 Merkle doc tree) and
> `data/ontology_column_config/` (the R11 per-column config). Each store's own
> docstring declares it a *version-controllable artifact* — reviewable in a diff and
> shippable to a teammate — so a new file appearing there after you run the app is
> the artifact asking to be reviewed, not stray runtime state. Commit it if it
> describes a connection worth sharing; otherwise leave it untracked. Don't add them
> to `.gitignore`: `data/*.json` is non-recursive on purpose so these nested files
> stay trackable, and ignoring them once silently negated a whole wave's
> distribution mechanic.
>
> **This repo is public.** These artifacts carry table and column names, so if you
> connect a private dataset, keep its artifacts out of the tree by pointing the
> stores somewhere else rather than ignoring them — `AUGHOR_ONTOLOGY_DOCS_DIR` and
> `AUGHOR_COLUMN_CONFIG_ROOT` are read at call time:
>
> ```bash
> export AUGHOR_ONTOLOGY_DOCS_DIR=~/.aughor/ontology_docs
> export AUGHOR_COLUMN_CONFIG_ROOT=~/.aughor/ontology_column_config
> ```
>
> Both are rebuilt on demand (the doc tree is Merkle-checksummed and incremental),
> so deleting a generated tree costs a rebuild, not data — unless an entry carries
> `source: human`, which a defaults refresh never overwrites.

## Running the checks

CI runs exactly these four jobs. Run them locally before opening a PR:

```bash
# 1. Backend tests — hermetic, no LLM. 10-12 min (serial; xdist is not configured).
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

Two tests are not offline: `test_xlsx_reads` and `test_listed_and_queryable_when_flag_on`
need DuckDB's `excel` and `sqlite_scanner` extensions, which DuckDB downloads from
`extensions.duckdb.org` on first use. They run normally once the extension is fetched or
cached, and **skip with the reason named** when it cannot be — so a green run on a locked-down
machine shows two skips rather than two failures. The `duckdb_extension` fixture in
`tests/conftest.py` is how; use it for any new test that needs one.

### A dirty lockfile after `npm install`

`web/package-lock.json` was written by npm 11, which records a `libc` field on
platform-specific optional deps. npm 10 — what Node 20 bundles, and what CI runs — drops
those fields on any `npm install`, so the file comes back dirty with ~30 deletions you did
not make. `npm ci` is unaffected either way, so CI does not care; just don't commit that
diff. Pinning the project to one npm (`packageManager` in `web/package.json`) would settle
it, but it means choosing which npm the project targets — and CI's install step is written
against npm 10 on purpose.

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
