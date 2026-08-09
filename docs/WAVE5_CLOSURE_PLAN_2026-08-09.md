# Wave 5 closure — wiring converse into `/ask` (plan of record, 2026-08-09)

Everything except the wiring is merged-ready on [#282](https://github.com/sidhasadhak/aughor/pull/282):
transport tool-calling (live-verified), `run_tool_loop`, the guarded tool set, `converse()`,
the `ask.converse` flag, and the ten-turn receipt. **Nothing calls `converse()` yet** — the
flag is inert by construction.

This document exists so the next session **decides** the one architectural question up front
instead of discovering it halfway through a 1300-line file.

---

## 1. The blocker, measured (not estimated)

Two obstacles were flagged when this was deferred. **One of them turned out not to exist.**

| Claimed blocker | Reality (measured 2026-08-09) |
|---|---|
| `_stream_chat` takes a FastAPI `Request`, so a tool can't call it | ❌ **False alarm.** `request` appears exactly once in lines 1266–2674: the signature. It is **never used in the body** (the only other hit is the English word "requested" in a string). It is a dead parameter with **2 call sites**. |
| It's an async generator; `run_tool_loop` is sync | ✅ **Real, and the only real one.** |

So the work is smaller than feared. **Do not re-derive this — verify it once and move on:**

```bash
awk 'NR>=1266 && NR<=2674' aughor/routers/investigations.py | grep -n "request"
```

Expect two hits: the signature, and `"…best guess was requested; "`.

## 2. The architectural decision — make it FIRST

**Recommendation: decompose into a SYNC core + a thin ASYNC SSE wrapper.** Reasons, in order
of weight:

1. **The work inside is already sync.** `provider.complete()` and `complete_with_tools` are
   blocking calls; `execute_guarded` is sync. The `async def` on `_stream_chat` buys the
   *streaming interface*, not the computation. It is sync work wearing an async coat.
2. **It matches the repo's existing bridge.** `routers/metrics.py` (3 sites) and `api.py`
   already do async-route → `loop.run_in_executor(None, _work)`. There is **no** precedent
   for `asyncio.run` / `run_until_complete` anywhere in `aughor/` — do not introduce one.
3. **It makes parity structural.** `answer_question` (sync tool) and the SSE route both call
   the same core. The invariant then holds *by construction*, which is strictly stronger than
   asserting two paths agree.

**Rejected alternative:** making `run_tool_loop` async. It would force every converse call
site async for no gain — the loop's own work is blocking either way — and it would make the
faux-backed tests (currently plain sync functions) markedly harder to read.

## 3. Order of operations

Each step ends green; do not batch them.

1. **Delete the dead `request` parameter** from `_stream_chat` and its 2 call sites
   (`investigations.py:3491`, `:3922`). Its own commit — a pure, reviewable subtraction that
   shrinks the surface before anything harder touches it.
2. **Extract the core.** `_answer_core(question, connection_id, history, *, session_id,
   canvas_id, skip_clarify, purpose, schema_scope, assumed_default) -> AnswerResult`, sync,
   returning the values the frames are built from (headline, sql, columns, rows, receipts,
   caveats, route). `_stream_chat` becomes a thin async generator that calls it and yields
   frames. **External behaviour must not change** — same frames, same order.
3. **Add the `answer_question` tool** to `converse_tools`, wrapping `_answer_core`. Its
   description is the routing policy: use it for a complete analytical question; use `run_sql`
   for a specific query you have already framed.
4. **Write the parity invariant.** Converse-wrapped `answer_question` and the direct fast path
   agree for the same question. Post-step-2 this is near-tautological — that is the point;
   the test exists to *keep* it that way.
5. **Emit converse SSE frames** and wire `/ask` behind `flag_enabled("ask.converse")`, fast
   path untouched when off.

## 4. Traps that are already paid for — do not rediscover

- **The frame-parity guard is live** (`tests/unit/test_sse_frame_parity.py`, PR #280). Any new
  converse frame must get a dispatcher `case` or an `UNRENDERED_FRAMES` entry **with a reason**,
  or CI fails. This is deliberate: nine frames were silently dropped before it existed.
- **134 `yield _sse(...)` sites** in `investigations.py`. Step 2 must preserve every one. The
  guard above catches drops; nothing catches a *reordering*, so keep the yields in the wrapper
  in their current order.
- **`ask.converse` must be read at CALL time**, never at import — a module-level read makes the
  flag unflippable in-process and turns `monkeypatch.setenv` into a no-op.
- **`data/llm_config.json` OUTRANKS `AUGHOR_BACKEND`.** Setting the env var does **not** make a
  script a dry run. Print the resolved binding before any call you believe is free.
- **A faux-backed test can only prove shapes faux can emit.** The `(completion, None)`
  pass-through bug passed 20 offline tests and metered every live turn as zero tokens. **Budget
  one live call per new transport shape** (`scripts/probe_tool_calling.py` is the pattern).
- **Never read `$?` after a pipe** — `npm run … | tail` reports `tail`'s status. Same masking
  that kept the cron tick green for two days.

## 5. Definition of done

- [ ] `/ask` serves a converse turn with `AUGHOR_ASK_CONVERSE=1`, and is byte-identical with it off
- [ ] Parity invariant green
- [ ] Frame-parity guard green (every new frame claimed or reasoned)
- [ ] Ten-turn receipt still green
- [ ] One **live** converse turn end-to-end (the faux lesson above)
- [ ] Full `Backend·pytest` green — CI is the authority, local fails both ways

Then `ask.converse` graduates on its stated exit: the receipt, the parity invariant, and
route-receipt data on the converse/fast-path ratio (Wave 6's input).
