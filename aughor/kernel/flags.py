"""Runtime feature flags — operator-toggleable, env-var fallback.

A handful of capabilities ship off-by-default because they cost (per-row LLM calls,
per-table version probes). They were previously env-only (`AUGHOR_AI_SQL`,
`AUGHOR_SNAPSHOT_RECEIPTS`), so an operator had to restart the process to flip them.
This stores an override in the kernel ledger kv so the UI can toggle them at runtime;
when no override is set, the env var still decides.

`flag_enabled(name)` is the resolver the feature code calls. The override is read from
SQLite per call (one indexed kv read — negligible; these aren't ultra-hot paths).
"""
from __future__ import annotations

import os

from aughor.kernel.ledger import Ledger

_STORE = "feature_flags"

# Registered flags: logical name → the env var that decides when no override is set.
FLAG_ENV = {
    "ai_sql": "AUGHOR_AI_SQL",
    "snapshot_receipts": "AUGHOR_SNAPSHOT_RECEIPTS",
    "explorer.synthesis_incremental": "AUGHOR_SYNTHESIS_INCREMENTAL",
    "specialist_packs": "AUGHOR_SPECIALIST_PACKS",
    "explore.parallel_subq": "AUGHOR_EXPLORE_PARALLEL",
    "ada.parallel_lenses": "AUGHOR_ADA_PARALLEL_LENSES",
    "ada.parallel_phases": "AUGHOR_ADA_PARALLEL_PHASES",
    "ada.why_where_interaction": "AUGHOR_ADA_WHY_WHERE_INTERACTION",
    "ada.why_deepen": "AUGHOR_ADA_WHY_DEEPEN",
    "ada.parallel_why_lenses": "AUGHOR_ADA_PARALLEL_WHY_LENSES",
    "preflight.parallel": "AUGHOR_PREFLIGHT_PARALLEL",
    "trust.verify_facade": "AUGHOR_TRUST_FACADE",
    "trust.verify_live": "AUGHOR_TRUST_VERIFY_LIVE",
    "semantic.resolve_live": "AUGHOR_SEMANTIC_RESOLVE_LIVE",
    "semantic.contract_live": "AUGHOR_SEMANTIC_CONTRACT_LIVE",
    "capability.pipeline_live": "AUGHOR_CAPABILITY_PIPELINE_LIVE",
    "ada.premise_check": "AUGHOR_PREMISE_CHECK",
    "ada.causal_drill": "AUGHOR_CAUSAL_DRILL",
    "ada.adversarial_verify": "AUGHOR_ADA_ADVERSARIAL",
    "ada.adversarial_high_stakes": "AUGHOR_ADA_ADVERSARIAL_HIGH_STAKES",
    "ada.pin_canonical_metric": "AUGHOR_ADA_PIN_CANONICAL_METRIC",
    "ada.progress_events": "AUGHOR_ADA_PROGRESS_EVENTS",
    "ada.clarify_gate": "AUGHOR_CLARIFY_GATE",
    "ask.clarify": "AUGHOR_ASK_CLARIFY",
    "closed_loop": "AUGHOR_CLOSED_LOOP",
    "semops.guarded_extract": "AUGHOR_GUARDED_EXTRACT",
    "join.key_reconciliation": "AUGHOR_JOIN_KEY_RECONCILIATION",
    "semops.champion_validate": "AUGHOR_SEMOPS_CHAMPION_VALIDATE",
    "federation.remote_join": "AUGHOR_FEDERATION_REMOTE_JOIN",
    "federation.planner": "AUGHOR_FEDERATION_PLANNER",
    "plan.program": "AUGHOR_PLAN_PROGRAM",
    "capability.contract": "AUGHOR_CAPABILITY_CONTRACT",
    "rbac.row_policy": "AUGHOR_RBAC_ROW_POLICY",
}

# A flag whose env var is UNSET resolves to its default (False unless listed).
# `ask.clarify` shipped default-ON (`os.getenv("AUGHOR_ASK_CLARIFY", "1")` at the
# old call site), so registering it here must not flip the live default.
FLAG_DEFAULT = {
    "ask.clarify": True,
}

# Human-facing copy for the Settings UI.
FLAG_META = {
    "ai_sql": {
        "label": "In-SQL AI operators",
        "description": "Register the governed prompt()/embedding() UDFs and let the generator use them. Makes per-row LLM calls — enable deliberately.",
    },
    "snapshot_receipts": {
        "label": "Snapshot-pinned receipts",
        "description": "Pin every finding to the exact data version it ran against (reproducible-as-of). The version probe touches the DB on each emit.",
    },
    "explorer.synthesis_incremental": {
        "label": "Incremental synthesis",
        "description": "Fire cross-finding synthesis the moment a new finding creates a combinable pair, not only at end-of-run. More 'alive', more compute. Phase 9 always runs at end-of-run regardless.",
    },
    "specialist_packs": {
        "label": "Specialist Agents (Domain Expertise Packs)",
        "description": "Load user-built specialist packs (packs/) and let them steer the engine at intake. Off by default while the subsystem lands — see docs/DOMAIN_EXPERTISE_PACKS.md.",
    },
    "explore.parallel_subq": {
        "label": "Parallel explore sub-questions",
        "description": "Run independent explore sub-questions concurrently in dependency-respecting waves (map-reduce over the operator.add state) instead of one-at-a-time. Cuts wall-clock on multi-cut investigations; multiplies concurrent LLM calls (bounded by the fan-out width cap + the P6 token budget). Off by default — see docs/PARALLEL_MULTIAGENT_GROUNDWORK.md.",
    },
    "ada.parallel_lenses": {
        "label": "Parallel Deep-Analysis lenses",
        "description": "For a cross-sectional Deep-Analysis ('why is X high/low'), run independent investigative lenses (segment/where ∥ mechanism/why) concurrently instead of one bundled scan — a deeper, multi-angle answer at ~flat wall-clock. Multiplies concurrent LLM calls (bounded by the P6 token budget). Off by default — see docs/PARALLEL_MULTIAGENT_GROUNDWORK.md.",
    },
    "ada.parallel_phases": {
        "label": "Parallel Deep-Analysis phases",
        "description": "Run the temporal investigation's middle phases (baseline ∥ decomposition ∥ dimensional) as one concurrent wave instead of a serial chain, keeping the serial tier-routers' early-stop semantics post-hoc (anything the serial path would have skipped is dropped from the report). Behavioral stays sequential — it targets the dimensional dominant finding. Cuts deep-run wall-clock; multiplies concurrent LLM calls (bounded by the P6 token budget). Off by default.",
    },
    "ada.why_where_interaction": {
        "label": "WHY×WHERE interaction lens",
        "description": "After the parallel WHERE and WHY lenses, forward-chain one more query crossing the leading return reason with the highest-impact segment — does the cause concentrate where the metric is worst (→ target that segment) or is it uniform (→ a broad problem)? Turns two independent findings into the actionable link. Adds one LLM-planned query per qualifying run; requires 'Parallel Deep-Analysis lenses'. Off by default.",
    },
    "ada.why_deepen": {
        "label": "Deepen the WHY (benchmark + drill)",
        "description": "After the WHY lens finds the leading return reason, forward-chain two more queries: a PEER BENCHMARK (is the reason's share abnormally high for the subject vs its peers, or a brand-wide baseline?) and a SECOND-LEVEL DRILL (which brands/products concentrate the leading reason — the fix target?). Establishes whether the cause is real and where to act. Adds two LLM-planned queries per qualifying run; requires 'Parallel Deep-Analysis lenses'. Off by default.",
    },
    "ada.parallel_why_lenses": {
        "label": "Parallel WHY-deepening lenses",
        "description": "Run the forward-chained WHY lenses (WHY×WHERE interaction ∥ peer benchmark ∥ reason drill) as one concurrent wave instead of a serial chain. Each depends ONLY on the already-computed WHERE/WHY summaries, never on each other, so the merge is byte-identical (fixed spec order, never completion order) — just faster wall-clock when two or more are enabled. Multiplies concurrent LLM calls (bounded by the P6 token budget); requires 'Parallel Deep-Analysis lenses' + the WHY lenses it parallelizes. Off by default.",
    },
    "preflight.parallel": {
        "label": "Parallel plan-time retrievals",
        "description": "Run the plan_queries pre-flight retrievals (relevant-schema ∥ KB planning patterns ∥ causal context ∥ closed-loop corrections) concurrently instead of one-at-a-time. All four are independent, deterministic, non-LLM lookups, so the result is byte-identical — just less wall-clock (a near-free win, no extra model cost). Off by default.",
    },
    "trust.verify_facade": {
        "label": "Unified trust.verify façade",
        "description": "Route SQL validation through the one Trust-plane façade (aughor/trust) — one Verdict composing the read-only/mutation gate, E1 footguns, preflight repair, and value-domain/fan-out probes — instead of a per-path guard subset. Adds the AST read-only gate to the /query/validate surface (closes SEC-02 there). Off by default while the plane lands (AL-01).",
    },
    "trust.verify_live": {
        "label": "Trust plane on the deep answer path",
        "description": "In the Deep-Analysis executor, route every generated SQL through trust.verify before execute — the AST read-only BLOCK the generation path never ran (defence-in-depth; the connection layer is already fail-closed). A blocked statement returns a blocked result instead of executing. Off by default (AL-01 live migration).",
    },
    "semantic.resolve_live": {
        "label": "Semantic plane resolved at the router",
        "description": "Resolve the Semantic plane (metrics · ontology · profile · KB) once when a deep investigation is seeded and attach the SemanticContext to the run state, so every node reads one consistent context instead of re-consulting ad-hoc. Off by default (AL-05 live migration).",
    },
    "semantic.contract_live": {
        "label": "Unified metric contract (planning)",
        "description": "Render the governed-metric grounding block from the one SemanticContract type (catalog ∪ profile north-star ∪ ontology, deduped by precedence) instead of the parallel CanonicalMetric shape. Byte-identical output today — this repoints the planning path at the single metric contract, the 20-year ontology bet's type unification (REC-U10). Off by default while the migration lands.",
    },
    "capability.pipeline_live": {
        "label": "Capability plane answer path",
        "description": "Enable the end-to-end Capability-plane answer path (/query/capability-answer): a data question runs generate → validate (trust.verify) → execute → interpret through the one CapabilityPipeline template. Off by default (AL-02 live migration).",
    },
    "ada.premise_check": {
        "label": "Premise validation",
        "description": "A 'why is X so high/low' investigation validates the premise (subject vs overall/peers) BEFORE explaining it — questioning the question itself instead of assuming it. Adds one comparison query per qualifying run. Off by default.",
    },
    "ada.causal_drill": {
        "label": "Causal-dimension priority + WHERE→WHY drill",
        "description": "The cross-section scan floats diagnostic dimensions (reason/condition/defect) ahead of the descriptive taxonomy so they survive the query cap, and after localising WHERE it auto-drills event-only dims into the WHY composition lens instead of stopping. Only affects the serial scan path (inert when 'Parallel Deep-Analysis lenses' is on, which lands the same idea in-lens). Off by default.",
    },
    "ada.adversarial_verify": {
        "label": "Adversarial verify decision-changing verdicts",
        "description": "ReFoRCE-style confidence-tiered verification: when a deep analysis lands a DECISION-CHANGING verdict (a premise rejection — 'X is not the problem' — or an abstention — 'within normal variance'), spend ONE extra skeptic LLM call to try to REFUTE it before shipping; a survived refutation caps confidence and records the objection. Fires only on the few high-stakes conclusions, never per finding. Off by default (adds an LLM call to those runs).",
    },
    "ada.adversarial_high_stakes": {
        "label": "Adversarial verify — high-stakes only",
        "description": "The cheaper, materiality-gated tier of adversarial verification: challenge a decision-changing verdict (premise rejection / abstention) with one skeptic LLM call ONLY when it is asserted with HIGH confidence — the costly-if-wrong minority, and the only case where the HIGH→MEDIUM confidence cap can bite. Lets the refuter earn a place on the default path without paying an LLM call on the many MEDIUM/LOW verdicts. Off by default; supersedes 'Adversarial verify decision-changing verdicts' (the full tier) for cost.",
    },
    "ada.pin_canonical_metric": {
        "label": "Pin governed metric at Deep-Analysis intake",
        "description": "When a deep investigation parses a metric the connection already GOVERNS (curated catalog / north-star / verified ontology), pin the intake's formula to the governed one so the cross-section scan decomposes on a stable, canonical definition instead of a run-varying LLM guess (the count-vs-value 'refund rate' class that left the breakdown un-decomposable → 'cause remains unidentified'). Deterministic, fail-open: only replaces the LLM formula when a governed metric matches the label, its SQL is a bare substitutable aggregate, and a dry-run confirms it runs over the metric table. Off by default = byte-identical.",
    },
    "ada.clarify_gate": {
        "label": "Interactive metric-ambiguity clarify (Deep-Analysis)",
        "description": "When a deep investigation finds that a metric's GOVERNED reading and the LLM's parsed reading both run but give materially different numbers (the count-vs-value 'refund rate' class), PAUSE before the scan and ask the user which reading they meant — instead of silently choosing one. The choice binds the metric for the run and is crystallized to the Ambiguity Ledger (source=user), so the same question never re-asks on that connection. Mirrors the plan-gate interrupt/resume. Off by default; asks at most once per run, only on a real divergence.",
    },
    "ada.progress_events": {
        "label": "Live per-dimension Deep-Analysis progress",
        "description": "Stream a per-dimension progress event as each query of a Deep-Analysis scan completes, so a long cross-section/decompose phase reports 'scanning brand (3/6)…' DURING execution instead of a multi-minute silent spinner between phase_complete events. Interleaves a lightweight progress marker into the SSE stream via a best-effort in-process sink (no extra model cost, graph events never dropped). Off by default = byte-identical stream.",
    },
    "ask.clarify": {
        "label": "Ask-vs-guess clarification",
        "description": "When a fresh question is materially ambiguous, ask ONE targeted clarifying question instead of guessing (deterministic under-spec + value-term detection; budget one ask per turn). ON by default — disable to always answer immediately.",
    },
    "closed_loop": {
        "label": "Closed-loop corrections",
        "description": "Read captured human corrections/verdicts and trusted queries back into the planner as priors, so a corrected mistake isn't repeated. Off by default until its delta is proven on your data.",
    },
    "semops.guarded_extract": {
        "label": "Guarded extraction (validate + re-extract)",
        "description": "When the semantic extract operator pulls a typed value (year/date/email/number) out of free text, validate each value against its type and re-extract the off-type cells with targeted feedback (a bounded gleaning loop). Off-type values are surfaced and kept, never dropped. Adds a re-extract LLM call only when a typed field fails validation. Off by default — turns text extraction from regex-fragile into a guarded, self-correcting step.",
    },
    "join.key_reconciliation": {
        "label": "Ill-formatted join-key reconciliation",
        "description": "When a join's two keys have low value overlap, try deterministic normalizations (trim/case, digits-only, strip prefix, strip leading zeros) and, if one lifts overlap over a bar, surface the exact expression to join on — distinguishing 'same entity, different format' (bid_123 vs bref_123) from genuinely different entities. Only runs when a value-domain mismatch already fired (rare); deterministic, fail-open, no LLM. Off by default = byte-identical (the mismatch warning is unchanged).",
    },
    "semops.champion_validate": {
        "label": "Champion cascade on semantic filter",
        "description": "The semantic filter operator runs on the cheap tier; with this on, a small spread sample of its verdicts is re-judged by the strong 'champion' model and the whole batch is escalated to the champion when they disagree beyond a bar — catching cheap-tier errors at the cost of one extra sample call per filter. Off by default = byte-identical (no validation sample). A label-free quality estimator in the Palimpzest/LOTUS lineage.",
    },
    "federation.remote_join": {
        "label": "Cross-source batched-foreach join",
        "description": "Enable POST /query/cross-source-join — join a result from one connection to a table on another, N+1-free (dedup the join keys, one keyed batch query per key-chunk to the right source, hash-join in memory). The correct-by-construction path for true cross-engine joins (Snowflake↔BigQuery↔Postgres) that DuckDB ATTACH can't reach. Off by default → the route 404s. Stage 1 of the cross-source federated planner.",
    },
    "federation.planner": {
        "label": "Cross-source federated planner",
        "description": "Enable POST /query/federated-answer — answer a natural-language question that spans TWO connections. One LLM call grounds both schemas and emits a structured plan (a grounded sub-query per source + the join keys); the plan is validated deterministically (each sub-query executes and outputs its key) and executed through the batched-foreach engine. Plan-then-execute, guarded, inspectable (the plan is returned). Off by default → the route 404s. Stage 3 of cross-source federation.",
    },
    "capability.contract": {
        "label": "Connector-capability contract",
        "description": "When a generated query FAILS on a native-SQL warehouse (BigQuery/Snowflake/MySQL), name the exact unsupported construct (QUALIFY/ILIKE/SAFE_DIVIDE/DATE_TRUNC/…) in the SQL-repair prompt so the regeneration fixes it precisely instead of another blind dry-run. A deterministic per-dialect capability descriptor + AST check; advisory (enriches the existing repair loop only), no LLM. Off by default = no extra hint. Rec 6 of the external-sources study.",
    },
    "rbac.row_policy": {
        "label": "RBAC row-level policy (row filters in the WHERE)",
        "description": "Compile per-role, per-table row-filters into executed SQL (a deterministic AST rewrite wrapping each policied table as a filtered subquery) so a role physically cannot read rows outside its filter. Double-gated like the rest of RBAC (no-op unless identity AND the org's RBAC_SSO capability are on) AND this flag; fails CLOSED (a policy that can't be applied blocks the query). Enforced at every connector's execution gate (DuckDB/Postgres/warehouse/file/API). Off by default. Rec 7 of the external-sources study.",
    },
    "plan.program": {
        "label": "Plan-as-program executor",
        "description": "Enable POST /query/plan-run + /query/plan-answer — turn a question into a deterministic typed PROGRAM over ONE database. One LLM call emits an ordered list of DATA (grounded SQL) + SEMOP (semantic-operator) steps over named artifacts; the program is validated deterministically and run step-by-step through the guard battery, threading each step's result as a named, versioned ledger artifact. Plan-then-execute, guarded, inspectable + replayable (the plan + artifacts are returned). Off by default → the routes 404. Rec 4 (plan-as-program), Stage 2–3.",
    },
}


def _env_resolved(name: str) -> bool:
    """Env-var value with the flag's default semantics.

    Default-off (the norm): unset ⇒ False, set ⇒ must be an explicit truthy value.
    Default-on (FLAG_DEFAULT): unset ⇒ True, set ⇒ off only on an explicit falsy
    value — preserving the old `os.getenv(var, "1") not in (off-list)` call sites
    byte-for-byte.
    """
    var = FLAG_ENV.get(name, "")
    raw = os.getenv(var)
    if raw is None:
        return FLAG_DEFAULT.get(name, False)
    if FLAG_DEFAULT.get(name, False):
        return raw.strip().lower() not in ("0", "false", "no", "off")
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _override(name: str):
    return Ledger.default().kv_get(_STORE, name, None)


def flag_enabled(name: str) -> bool:
    """The effective value: a runtime override wins; otherwise the env var decides."""
    ov = _override(name)
    if ov is not None:
        return bool(ov)
    return _env_resolved(name)


def set_flag(name: str, value: bool) -> None:
    """Set a runtime override (wins over the env var until cleared)."""
    Ledger.default().kv_put(_STORE, name, bool(value))


def clear_flag(name: str) -> None:
    """Drop the override so the env var decides again."""
    Ledger.default().kv_put(_STORE, name, None)


def list_flags() -> dict:
    """All registered flags with their effective value + source, for the Settings UI."""
    out = {}
    for name, var in FLAG_ENV.items():
        ov = _override(name)
        meta = FLAG_META.get(name, {})
        out[name] = {
            "value": bool(ov) if ov is not None else _env_resolved(name),
            "source": "runtime" if ov is not None else "env",
            "env_var": var,
            "label": meta.get("label", name),
            "description": meta.get("description", ""),
        }
    return out
