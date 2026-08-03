# Scope — a hosted demo anyone can land on

**Status:** scoped, not started. 2026-08-03.

## The gap this closes

`aughorintelligence.vercel.app` serves the UI but has no backend. `NEXT_PUBLIC_API_URL` is
unset, so it falls back to `http://localhost:8000` — which, for a visitor, is their own
machine, running nothing. **Today the deployed site is a shell.**

A hosted demo means: land on the URL, see a real investigation against real data, with no
install. That needs a backend somewhere Vercel cannot host it.

## Measured, not assumed

| Fact | Value |
|---|---|
| Dev venv (what Vercel tried to bundle) | 1,088 MB |
| **Core-only install** (29 deps, no extras) | **625 MB** |
| Vercel serverless function ceiling | 500 MB — still over, hence a container |
| Seeded demo DB `data/aughor.duckdb` | **2.0 MB** |
| `data/samples.duckdb` | 1.5 MB |

**The demo data ships inside the image.** At 2 MB it needs no volume, no external
database, no migration story — `COPY` it in and mount nothing. That removes the single
biggest source of hosted-demo complexity before it starts.

Core-only drops 463 MB by excluding extras that a demo never touches: `connectorx`
(113 MB) and the rest of `[warehouse]`, `mlflow` from `[observability]`, `[evals]`,
`[crm]`, `[cloud-storage]`, `[knowledge-sync]`, `[docs]`. What remains is genuinely core:
polars 193 · scipy 72 · duckdb 44 · pandas 40 · grpc 39 · statsmodels 37 · matplotlib 24 ·
numpy 22. These measurements are macOS wheels; Linux wheels are typically smaller, so 625 MB
is a ceiling rather than a target.

Further trimming worth testing, in order of likely payoff:
- `grpc` (39 MB) arrives via `qdrant-client`; the demo may not need the vector store at all.
- `matplotlib` (24 MB) + `PIL` (15 MB) are export/chart rendering — only needed if the demo
  offers PDF/PPTX export.
- `statsmodels` (37 MB) and `scipy` (72 MB) back the statistical guards. Check what actually
  imports them on the ask path before assuming they are required.

## What is already safe (and it is more than expected)

**Read-only is unconditional.** `aughor/trust/__init__.py::_verify_sql` runs
`readonly.is_mutating()` as a **BLOCK**-severity check, and the code comment is explicit
that it is called directly rather than through a `tolerate()` so "a mutation verdict must
never be swallowed". Disallowed functions are blocked the same way. Wave 2a hardwired
`trust.verify_live`, so there is no flag to leave off. A visitor cannot write to the demo
database through generated SQL.

**Spend caps exist.** `aughor/govern/usage_caps.py` provides `evaluate`, `check`,
`observed_usage`, `effective_limit`, with `UsageCap.applies_to(org_id, user_id)`.
`govern.usage_caps` and `ops.metered_monitors` are both hardwired as of Wave 2c.

**Auth is optional and off.** `AUGHOR_API_KEY` unset ⇒ no gate, which is what a public demo
wants. Note the corollary from the runtime-API-base work: the frontend sends no key, so the
gate cannot be turned on for the demo without frontend work.

## The real risks, in the order they will bite

### 1. Spend. This is the one that can actually hurt.

A public endpoint running live model calls is someone's bill. Caps are per **org/user**, and
every anonymous visitor is effectively the same org — so one org-wide cap is a shared
bucket that a single heavy user (or a script) drains for everyone. **There is no per-IP or
per-session rate limiting in the codebase** (checked: no `rate_limit`, `slowapi`, or
`X-Forwarded-For` handling outside `llm/provider.py`'s own retry logic).

Needed before exposure, roughly in this order:
- a hard org-level daily cap, set low, as the backstop that cannot be argued with
- per-session throttling (a cookie/session id) so one visitor cannot drain the day
- a cheap model binding for the demo specifically — `data/llm_config.json` is the authority,
  not `.env`
- ideally: precomputed answers for the starter questions, so the common path costs nothing
  (see "Cheapest viable version" below)

### 2. Shared mutable state

`/ask` writes: `save_chat_turn`, `complete_investigation`, the trust receipt, the ambiguity
ledger. Read-only SQL does **not** mean a read-only service — every visitor appends to the
same history, investigations list, and event journal. Options: ephemeral per-container state
(restart wipes it), per-session scoping, or accepting a shared, visibly-messy demo. This
needs a decision, not a default.

### 3. CORS

The API must allow `https://aughorintelligence.vercel.app`. `AUGHOR_CORS_ORIGINS` exists.
Do **not** set `*` — pair it with the origin explicitly.

### 4. Cold starts

The container seeds DuckDB at boot if the file is absent. Baking the 2 MB DB into the image
avoids that entirely — worth doing for a demo where first impression is the product.

## Which dataset

The bundled scenario (`aughor/demo/scenario.py`) is purpose-built for this: 90 days, ~800
customers, deterministic seed 42, a planted root cause (day 83 APAC payment-gateway outage →
verified −38.8% APAC/SMB drop) **and a red herring** (an NA promotion three days earlier that
does not explain it). Its docstring records why it exists — a bland dataset made the
first-run Briefing narrate a non-finding (W14).

That decoy is the demo. It shows the agent rejecting a plausible alternative, which is the
capability a chart tool cannot claim.

**Superstore as a second, additive dataset** is worth it for a different reason: familiarity
is a trust device. A visitor who knows Superstore can audit the finding against what they
already believe, where a synthetic dataset asks them to take the vendor's word. Its known
tables-lose-money-to-discounts story lands directly on the shipped
`where_are_we_losing_money` starter and exercises `intake.loss_signals`. Hero = the SaaS
scenario; credibility check = Superstore. Not a replacement.

## Cheapest viable version (recommended first cut)

Do not start by hosting a live agent. Start by hosting a **frozen** one:

1. Run the three shipped starters against the bundled scenario **offline**.
2. Ship the resulting investigations as seeded, read-only artifacts in the image.
3. The landing page opens a finished investigation — receipts, charts, the rejected red
   herring, all real output from a real run.
4. Live asks stay behind "connect your own backend" (already built, PR #251).

Cost: near zero. Risk: near zero. It demonstrates the actual product — the reasoning and the
receipts — without exposing a spend surface to the internet. If the frozen demo converts,
the live version becomes a funded decision rather than a speculative bill.

## Estimate

| Piece | Size |
|---|---|
| Dockerfile, core-only deps, DB baked in | small |
| CORS + config for the hosted origin | small |
| **Frozen-artifact demo path** (recommended first cut) | small-to-medium |
| Per-session throttling + demo cap posture | **the real work, if going live** |
| Session-scoped or ephemeral write state | medium, and needs a product decision |
| Superstore as a second dataset | small (loader + a starter) |

## Pre-check before building

1. **Confirm what the ask path actually imports.** If `scipy`/`statsmodels`/`matplotlib` are
   not on the demo's hot path, the image drops another ~130 MB. Measure with an import trace
   on a real ask, do not reason from the dependency list.
2. **Decide the write-state posture before exposing anything.** Ephemeral vs session-scoped
   vs shared changes the container's statefulness, and retrofitting it after launch means a
   migration on live demo data.
