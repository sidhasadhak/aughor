# `_answer_core` extraction map — verified against source (2026-08-09)

Four parallel readers over `_stream_chat`, each adversarially verified against the
file before synthesis. Where a reader and its verification disagreed, the verification
won. Line numbers re-derived at HEAD, not inherited.


# Extraction map: `_stream_chat` → `_answer_core`

## 0. Corrections that change the design

| Claim | Verdict |
|---|---|
| "47 yields" (report *state*) | **Wrong — 49.** AST over the generator body excluding 13 nested defs/9 lambdas: `[1312,1317,1512,1513,1514,1681,1682,1683,1693,1758,1759,1829,1855,1903,1904,1905,1913,1914,1949,2081,2114,2124,2125,2133,2151,2168,2183,2214,2223,2236,2237,2239,2240,2242,2243,2245,2247,2249,2257,2324,2328,2345,2490,2495,2507,2512,2525,2548,2558]`. Verifications are right. |
| "Four of six early exits emit `done`" (report *yields*) | **Wrong — three of six.** Returns are `[1313,1318,1529,1697,1760,2126]`; `done` precedes only 1529, 1697, 1760. |
| "Three `return`s bypass the guard battery" (report *bug*) | **Wrong — five.** 1313/1318 return before any guard exists. |
| "10 top-level statements" (report *bug*) | **Wrong — 11** (`len(fn.body)==11`). Its own enumeration sums to 11. |
| **"The bridge trap is contextvars; `run_in_executor(None,…)` drops them"** (report *threads*) | **Materially outdated at this HEAD.** `aughor/api.py:264 _install_context_executor` sets a `ContextThreadPoolExecutor` as the loop's **default** executor at `api.py:94`, so `run_in_executor(None,…)` *does* propagate in the live API. The commit at HEAD (`0948ac4`) exists precisely to guard that ordering. The trap is real but inverted: **the core is now safe in-process and unsafe out of it** — tests, MCP, and any non-lifespan caller get the stdlib executor. Use `asyncio.to_thread` for the bridge (copies context unconditionally) rather than depending on install order. |

Everything else in the four reports that I mechanically checked holds, including the entire phase map, all 9 `guard_receipt` sites, the 22 `to_thread` sites, and both `domain_table_cols` proofs.

---

## 1. `_answer_core` signature and return type

`request: Request` (param 4) is **dead** — zero `Name` references in 1266–2565 (only the substring "requested" in a string at 2304). It cannot simply be deleted from `_stream_chat`, because both call sites pass it **positionally**: `investigations.py:3491` and `:3922`. Drop it from the core, keep it on the wrapper.

```python
def _answer_core(
    question: str,
    connection_id: str,
    history: list[ChatHistoryTurn],
    *,
    emit: Callable[[str, dict], None],
    session_id: str = "",
    canvas_id: Optional[str] = None,
    skip_clarify: bool = False,
    purpose: str = "",
    schema_scope: Optional[str] = None,
    assumed_default: bool = False,
) -> _AnswerCoreResult:
```

`emit(type, payload)` mirrors `_sse` (line 67): `{'type': event_type, **data}` — payload is spread **flat**, so a payload key named `type` *overwrites* `event_type`. Keep that shape so the wrapper is `_sse(t, p)` verbatim.

### The return type — and the one field the reports get wrong by omission

The *state* report concludes the core "must hand back an ordered emission log, not a result struct." That is half right. `emit` **is** the ordered log. The struct carries terminal state. But this split has a consequence nobody flagged:

> **With a no-op emit, `answer_question` loses all 9 `guard_receipt` frames.** The existing sibling tool `run_sql` (`aughor/agent/converse_tools.py:55–65`) returns `guard_receipts` and `caveats` *in its dict*, and the converse system prompt (`converse_tools.py:196–202`) instructs the model to narrate exactly those. A core that emits receipts and returns only the answer makes `answer_question` strictly weaker than `run_sql` at the thing the product exists to do.

So receipts must be **accumulated into the return**, not merely emitted:

```python
@dataclass
class _AnswerCoreResult:
    outcome: str            # "answered"|"not_found"|"connect_failed"|"kb_definitional"
                            # |"abstained"|"clarify"|"query_failed"
    headline: str           # _grounded_headline AFTER 2238 currency pass — never answer.headline
    sql: str                # final_sql FINAL value (6 stores: 1835,1900,1947,2056,2069,2112)
    columns: list; rows: list; row_count: int | None
    guard_receipts: list[dict]      # the 9 payloads, in emission order  ← REQUIRED, see above
    error: str | None = None        # result.error (2125 path)
    mode: str | None = None         # "final_text" on the two no-SQL paths only (1512,1681)
    chart_type: str = "auto"; chart_config: dict = field(default_factory=dict)
    intent: str = ""; approach: list[str] = field(default_factory=list)
    tables_used: list = field(default_factory=list)
    clarify: dict | None = None     # _sv.to_event() (1758)
    escalate: dict | None = None    # _esc — two DIFFERENT derivations, see §4
    inv_id: str | None = None; receipt_id: str | None = None
    trusted: list = field(default_factory=list)      # _trusted_used (1623–1633)
    playbook_refs: list = field(default_factory=list)
    narrative: dict | None = None; followups: list = field(default_factory=list)
```

`headline`/`chart_type`/`chart_config`/`intent`/`approach` come from `_ChatAnswer` (`investigations.py:952–961`). **Copy them out — do not return `answer` by reference**: it is mutated in place at 2221 (`chart_type`) and 2235 (`chart_config`).

**Judgment vs. measurement:** the field *set* above is a design proposal. What is measured and non-negotiable: `request` is dead; `guard_receipts` must be in the return; `headline` must be the post-2238 value; `answer` must be copied not aliased.

---

## 2. Emit-site inventory — 49 sites, 16 phases

Only **7 are unconditional** (2081, 2236, 2237, 2239, 2240, 2243, 2345) — and all 7 sit inside `Try@1324`, so "unconditional" ≠ "always reached". **42 of 49 are conditional, loop-nested, or in an exception handler.**

| Phase | Lines | Sites | Frames |
|---|---|---|---|
| P0 connect (**outside** `Try@1324`) | 1298–1322 | 2 | `error` 1312 (`not_found`), `error` 1317 |
| P1 context gather | 1324–1484 | 0 | — |
| P2 KB fast path → `return 1529` | 1491–1533 | 3 | `mode` 1512, `headline` 1513, `done` 1514 |
| P3 prompt assembly | 1535–1647 | 0 | — |
| P4 abstention → `return 1697` | 1656–1697 | 4 | `mode` 1681, `headline` 1682, `done` 1683, **`followups` 1693 (after `done`)** |
| P5 compiler hint | 1704–1729 | 0 | — |
| P6 clarify → `return 1760` | 1745–1762 | 2 | `clarify` 1758, `done` 1759 |
| P7 generation | 1771–1860 | 2 | **`headline_delta` 1829 (loop)**, `compiled` 1855 |
| P8 pre-exec guards | 1862–2079 | 6 | `sql` 1903, `fanout` 1904/1913, `guard_receipt` 1905/1914/1949 |
| P9 execute + repair | 2081–2126 | 4 | `sql` 2081, `sql` 2114, `escalate` 2124, `error` 2125 → `return 2126` |
| P10 post-exec caveats | 2128–2227 | 6 | `guard_receipt` 2133/2151/2168/2183/2214/2223 |
| P11 result | 2232–2257 | 10 | `columns` 2236, `rows` 2237, `headline` 2239, `chart_type` 2240, `chart_config` 2242, `tables_used` 2243, `analysis` 2245, `playbook_refs` 2247, `trusted` 2249, `escalate` 2257 |
| P12 persist + `done` | 2262–2345 | 3 | **dyn `_evt` 2324 (loop)**, `receipt_id` 2328, `done` 2345 |
| P13 narration — **after `done`** | 2352–2529 | 5 | **`narrative_delta` 2490 + `insight_delta` 2495 (loop)**, `narrative` 2507, `insight` 2512, `followups` 2525 |
| P14 inspect | 2540–2555 | 1 | `inspect_warning` 2548 |
| P15 outer handler | 2557–2558 | 1 | `error` 2558 (no `reason` — unlike 1312/2125) |

### Yields in loops (3 sites, 2 `while` + 1 `for`)
- **1829** `While@1818 > If@1827` — drains `_hl_q`; throttle `≥6` chars or `>120 ms`. N frames.
- **2490 + 2495** `Try@2354 > While@2478 > If@2487` — drains `_pa_q`; throttle `≥12` chars or `>150 ms`. N×**2** frames sharing one `_delta_payload` object; must stay adjacent and ordered.
- **2324** `If@2284 > For@2322 > If@2323` — **the only site whose frame *name* is a variable** (`_evt ∈ ("learning","activations")`). Invisible to a literal `_sse("` grep.

### Deepest nesting
5 levels: 1758/1759 (`If@1745 > Try@1746 > If@1749 > If@1751 > If@1757`). 4 levels: 1512–1514, 1903–1905, 2114, 2214, 2548.

### Ordering hazards the extraction will break first
1. **`done` at 2345 is not terminal.** Six frames follow on the happy path (2490, 2495, 2507, 2512, 2525, 2548). Deliberate — comment 2259–2261.
2. **`sql` fires up to 3× (1903 → 2081 → 2114)**, last-write-wins client semantics.
3. **P10's caveat guards mutate values emitted in P11.** 2144–2148 / 2161–2165 / 2176–2180 / 2202–2206 append to `_grounded_headline`; 2221 rewrites `answer.chart_type`; 2235 merges `_exh` into `chart_config`. Their receipts fire *before* the values ship at 2239/2240/2242. Hoisting emission drops the caveats silently.
4. **`headline_delta` 1829 carries the RAW pre-grounding headline**; 2239 is authoritative. Same self-healing contract for 2490 vs 2507.
5. **`mode` exists only on the two no-SQL terminal paths** (1512, 1681), never on the SQL path.

---

## 3. `to_thread`: what inlines, what does not

22 sites — `[1380, 1386, 1398, 1466, 1516, 1685, 1750, 1755, 1819, 1830, 1938, 1994, 2056, 2069, 2082, 2106, 2110, 2264, 2479, 2496, 2519, 2543]`. Exactly 22 `await` expressions total; no `async for`, no `async with`. **No offloaded target is itself async.**

### Does NOT inline — 1 site
**1398, inside the `asyncio.gather` at 1394.** The only real concurrency in the function: 8 independent producers (`_get_schema_cached` 1398 plus `_kb` 1345, `_ckb` 1350, `_sqlex` 1355, `_expl` 1359, `_causal` 1364, `_docs` 1369, `_pb_match` 1374). The parallelism is **not** GIL-bound — `_ckb` and `_docs` make Qdrant/Ollama HTTP calls, `_get_schema_cached` does live introspection on a miss. Inlining turns `max(t₁..t₈)` into `Σ(t₁..t₈)` on **every quick answer, before the first token**.

**Fix, not a regression to accept:** the sync core keeps the concurrency with `ContextThreadPoolExecutor` (`aughor/kernel/concurrency.py`), which is already the codebase's idiom for exactly this (`agent/phase_waves.py:57`, `llm/provider.py:2288`, `evals/flag_batch_a_receipt.py:116`) and copies contextvars per worker. Preserve two semantics: `_safe`/`_safe_list` (1378–1388) swallow to `""`/`[]`; and `gather` is `return_exceptions=False`, so a raise from the one unwrapped member (`_get_schema_cached`) propagates to 2557.

### Inlines, but only off the event loop — 4 sites
**1819, 1830, 2479, 2496.** These are *not* concurrency: the concurrency is `threading.Thread` (`_hl_thread` started 1806, worker `_hl_worker` 1792–1803; `_pa_thread` 2462, worker 2446–2458). The `to_thread` only moves a blocking `queue.get(True, 0.25)` off the loop. A sync core calls `_hl_poll()` directly and the producer thread keeps filling the queue — delta ordering, throttling and the sentinel protocol are all preserved.

**The worker threads must stay.** They are not incidental: `_hl_worker` closes over `_chat_system` (1785), `prompt`, `_hl_q`; `_pa_worker` over `_system`, `_user`, `_pa_q`. The property lost if the core runs *on* the loop is stated at 1773–1774 — and both `.join()` calls (1830, 2496) are **argument-free, no timeout**, so a hung provider wedges the whole server rather than one request.

### Inlines safely — 17 sites
`1380, 1386, 1466, 1516, 1685, 1750, 1755, 1938, 1994, 2056, 2069, 2082, 2106, 2110, 2264, 2519, 2543`. Each is a single `await` consumed within a few statements. `2056→2069→2082` is a hard `final_sql` chain; `2106→2110` is fix-then-retry.

Two get **safer**: the sqlite writers (1516, 1685, 2264, 2519) go through `db/history.py:69 _conn()` → `connect_store`, which defaults `check_same_thread=True` (`db/backend.py:70`) and opens a fresh connection per call — pinning them to one thread removes a latent footgun. Note the loop is *already* blocked by un-offloaded work regardless: `resolve_execution_scope` (1298), `_es.open()` (1306), `load_latest_ontology` (1462), `_resolve_answer` (1664), `compile_question` (1716), **`db.dry_run(_rw)` at 1897** (a live round-trip), `_write_answer_receipt` (2313).

**Correction to report *threads*, row 11:** line 2130 is not a yield — it is `_grounded_headline = _ground_headline(...)`. And the join's largest consumer is **1835** `final_sql = answer.sql`, omitted from its list.

**Cost correction to report *bug*:** "exactly two provider calls" counts `get_provider` sites (1796 coder, 2451 narrator), not round-trips. Also reachable: `SqlWriter.fix` → `writer.py:469` at 1939 (`max_retries=1`) and 2107 (`max_retries=2`), `preflight_repair` → `safety.py:112` at 2056, `_inspect_sql` → `inspect.py:122` at 2543, ambiguity probe → `ambiguity_probe.py:176` at 1750. Budget on ~7 call sites, not 2.

---

## 4. Early-return paths the core must reproduce — 6

| # | Return | Trigger | Frames, in order | Notes for the core |
|---|---|---|---|---|
| 1 | **1313** | `KeyError` from `_es.open()` (1306) | `error` 1312 `reason="not_found"` | **Outside `Try@1324`** → `finally` never runs, `db` unbound |
| 2 | **1318** | any other exception, same open | `error` 1317 `"Could not connect: …"` | same |
| 3 | **1529** | `kb_answer.strip()` (1506) | `mode` 1512, `headline` 1513, `done` 1514, then `save_chat_turn` 1516–1528 | no frame after `done`, but a blocking write is |
| 4 | **1697** | `feasibility=="not_answerable" and _abstain_ok` (1679) | `mode` 1681, `headline` 1682, `done` 1683, save 1685–1692, **`followups` 1693** | only terminal exit emitting a frame *after* `done`; followups are a **hardcoded** 2-item list (1694–1695) |
| 5 | **1760** | `_sv.ambiguous` (1757) | `clarify` 1758, `done` 1759 | **no turn saved.** Gated by `skip_clarify` at 1745 |
| 6 | **2126** | `result.error` (2120) | `escalate` 2124 (cond.), `error` 2125 `reason="query_failed"` | **no `done`** |

Plus the non-return termination at **2558** (`except Exception` of `Try@1324`) — `error` with **no `reason`**, falling back to the generic classifier. Four terminations end on `error` with no `done`: 1313, 1318, 2126, 2558.

**`_esc` is not one value re-derived.** 2122 passes `error=result.error`; 2255 does not. The two `escalate` sites are mutually exclusive; merging them folds the error branch into the success branch.

---

## 5. Riskiest part, and how to sequence around it

**The risk is not the yields. It is that the `try/finally` at 1324/2559 stops being a cancellation point.**

Today `db` is opened at 1306 and closed *only* in the `finally` at 2559–2565. On client disconnect, `StreamingResponse` closes the async generator → `GeneratorExit` raised at the current `yield` → `finally` → `db.close()`. Move the body onto a thread and **there is no cancellation point at all**: the thread has no `GeneratorExit`, both `.join()` calls are untimed, and nothing in 1266–2565 checks `request.is_disconnected()` (the param is dead). A disconnected client leaves an LLM stream, a repair round and a DB connection running to completion.

*Evidence quality: the absence of any disconnect check and the `finally`-only close are measured. The disconnect→GeneratorExit→finally chain is standard ASGI/asyncgen semantics, reasoned not measured — I did not run a disconnect test. Worth one before you commit to the bridge.*

Secondary risks, in order: (b) the two delta loops — emit ordering across the queue is where interleaving bugs hide; (c) the P10→P11 mutate-then-emit coupling; (d) the gather's latency if you inline it.

### Sequence

1. **Build the parity net first.** `tests/integration/test_insight_stream.py` already asserts the exact contract that will break: `headline_delta` before `done` (:126), deltas strictly *between* `done` and `insight` (:135), `insight` before `followups` (:136), dual-emit key equality (:159). Extend it to record the full 49-frame `(type, order)` sequence as a golden transcript across all 6 termination paths before touching the body. `tests/integration/test_resolve_first_runtime.py:62` covers path 4.
2. **Rename in place, no move.** `_stream_chat` keeps its body; add `emit` as a local that wraps `yield`. Not yet possible for a generator — so instead: mechanically replace all 49 `yield _sse(t, p)` with `emit(t, p)` and define `emit` to append to a list. Run the golden transcript against the list. This isolates "did I preserve order" from "did I preserve threading".
3. **Then** make it sync + thread bridge (`asyncio.to_thread(_answer_core, …)` — copies context unconditionally, independent of `_install_context_executor` ordering). Add an explicit disconnect/cleanup story for §5's risk.
4. **Then** restore the gather's concurrency via `ContextThreadPoolExecutor`. Measure prelude latency before/after — this is the one step with a numeric acceptance criterion.
5. **Last**, wire `answer_question` with a no-op emit, asserting `guard_receipts` is non-empty in the *return*.

### Two tripwires

- **`tests/unit/test_ask_quick_schema_scope.py:31`** asserts `"schema_scope=schema_scope" in inspect.getsource(_stream_chat)`. If the wrapper forwards `schema_scope=schema_scope` to the core, **this test passes vacuously** while the resolver call it was written to protect has moved to another function. Repoint it at `_answer_core` explicitly.
- **The two doors do not pass the same arguments.** 3491 (`/chat`) passes only `session_id`, `canvas_id`; 3922 (`/ask`) adds `skip_clarify`, `purpose`, `schema_scope`, `assumed_default`. So via `/chat` the clarify probe at 1745 is *always* armed, `guard:assumed_reading` (2300–2305) can never fire, and schema pinning never applies. The core inherits a **two-door contract**, not one.

Also carry, or you will silently change behaviour: `connection_id` is **rebound at 1300** (`_es.connection_id`); `_es` outlives the scope block (read at 1409, 1413); `_rcpt` is prompt input, not just receipt state — `_guard_note(_rcpt)` at **2432** goes into the narrator's user message; `prompt` has 11 stores (1554→1769) and exactly one read, at **1797** inside `_hl_worker`. Dead on arrival: `_pf_receipt` (assigned 2056, never read — which is why `preflight_repair` is the one guard that mutates `final_sql` with no receipt frame; `enforce_grounded_literals` at 2069 is the other silent mutation).

---

## 6. `domain_table_cols` — root cause and minimal fix

**Confirmed independently. The in-code comment is factually wrong on both of its claims.**

`aughor/explorer/agent.py`, `SchemaExplorer._phase8_domain_intelligence_inner` (2112–3981). `symtable`: `is_local=True, is_global=False, is_free=False, is_parameter=False`. Its **only** binding site is the annotated assignment at **2763**; 2784 and 2806 are subscript stores; 1956/1985 are parameters of *other* methods.

AST nesting proves the ordering:

```
2689 LOAD   For@2483 | While@2611 | Try@2673 | If@2680 | For@2689
2763 STORE  For@2483 | While@2611
```

The read at **2689** and the store at **2763** are in the **same `while` body** (2611–3981), 74 lines apart, read first.

```python
2689   for _tbl in domain_table_cols:  # noqa: F821
```

- **"never bound"** — false; 2763 binds it.
- **"always NameErrors / dormant"** — false. It fails **only on the first iteration of the `while` in a given invocation**; from iteration 2 onward the name is bound from the previous iteration and the nudge runs. It also stays bound across domains (`For@2483`), so it fires **at most once per invocation**.

**Reachability:** 2689 is gated by `len(_used_dims) >= 2` at 2680, built from `domain_insights` (seeded 2538–2540 from `self._state["insights"]`, loaded at construction, `agent.py:361`). So a **fresh** exploration never trips it (gate closed on iteration 1). A **re-run** over a connection/canvas whose stored state already holds ≥2 Phase-8 findings for the *first* domain, with ≥2 distinct GROUP BY columns, hits `UnboundLocalError` — swallowed by `except Exception` at 2704, logged via `tolerate` (`kernel/errors.py:44`) as `tolerated.explorer.diversity_nudge_failed`, leaving `diversity_block = ""`.

### Minimal fix
**Relocate lines 2664–2707 (including the `diversity_block = ""` initializer at 2672) to immediately after line 2813** — after the neighbour-FK augmentation (2794–2807) and the empty-dict log (2809–2813), before `domain_schema_block` at 2815. Delete the stale comment 2684–2688 and the `# noqa: F821`.

Safety, verified rather than asserted:
- `diversity_block`'s **only** consumer is the prompt f-string at **3105**, well after 2813.
- No `continue`/`break`/`return` exists at generator level in 2664–2830. (I found `Return` at 2682 and 2738 — both are inside the nested defs `_dnorm` (2681–2682) and `_tbl_ts` (2736–2738), so the *threads*-style claim of "no control flow" survives, but only after excluding nested scopes.)
- The five later reads (2809, 2888, 3072, 3120, 3128/3131) all sit after 2813 and are undisturbed.

**Do not fix by hoisting an initializer.** Both hoists are wrong in opposite directions: hoisting `= {}` before the `while` silences the exception but makes iteration 1 read an empty dict — `diversity_block` stays `""` *exactly on the iteration where prior findings exist and the nudge was wanted*. Hoisting to function scope leaks the **previous domain's** tables, naming another domain's columns as "unused dimensions" — precisely the invent-a-column hallucination the block's own rationale (2664–2671) exists to prevent.

**Regression test must assert two things**, because a hoist-init would pass a weaker one: seed `self._state["insights"]` with ≥2 findings whose `domain` is the *first* domain in `passes` and whose `sql` groups by two different columns, then assert (1) no `tolerated.explorer.diversity_nudge_failed`, **and** (2) `diversity_block` is non-empty and names a real low-cardinality non-FK non-id column belonging to *this* domain's tables — proving it read the populated dict, not `{}` and not a neighbour's. Add a fresh-run case (empty `insights` → gate closed → no nudge, no error) so the relocation cannot start firing the nudge where it previously could not.