# UI Elevation — 2026-07-14

*Status: research VERIFIED (primary sources), Wave 1 + Wave 2 implementation on branch
`agentic-platform`. Goal (user-stated): match the beauty/coherence of CopilotKit's offerings and
shadcn/ui — while keeping our shell, our SSE reducer, our token sheet, and the three CI design
gates. Companion to `docs/AGENTIC_PLATFORM_UNIFICATION_2026-07-13.md` (the conversational pillar).*

## Verdicts (adversarially verified 2026-07-14)

1. **shadcn/ui, harvested — not adopted as a framework.** As of July 2026 Base UI
   (`@base-ui/react` — ALREADY our dependency) is shadcn's **default** primitive backend; Tailwind
   v4 CSS-first theming via `@theme inline`; React 19 clean. Component-level copy-in honors the
   proven "unify + finish, NO new frameworks" rule. The repo already carries the full machinery
   (components.json, cva, clsx, tailwind-merge, `components/ui/*`) — it was simply never finished.
2. **Retheme = one bridge file.** Define shadcn's semantic vars (`--background/--card/--muted/
   --primary/--border/--input/--ring/--radius`…) as aliases onto tokens-v2 values in `:root`/dark,
   exposed via `@theme inline`. `--primary` binds to the INTERACTIVE blue only; the data blue stays
   reserved for charts. (A stale partial bridge existed — `--radius: 4px` — now re-pointed.)
3. **Chat kits: harvest prompt-kit (copy-in, transport-free, zero AI-SDK coupling) + Vercel AI
   Elements for gaps + official shadcn chat primitives as they stabilize. REJECT assistant-ui**
   (a chat framework: runtime + zustand + message adapters — it would own the chat state machine
   our reducer owns). Skip shadcn.io/ai (unofficial provenance).
4. **CopilotKit's beauty is ~25 replicable patterns, not their shell** (their react-ui remains
   rejected per the CK plan): composer pill (large-radius, shadow-only, two-state grid),
   send⇄stop morph, bubble asymmetry (user bubbles; assistant = full-width prose), turn rhythm via
   one big top gap, hover-revealed message toolbars, in-place copy confirmation, 11px pulsing
   stream cursor, block-safe markdown-as-it-streams, code-blocks-as-furnished-cards, floating
   scroll-to-bottom, status-driven tool/plan cards.
5. **Motion**: `tw-animate-css` is already installed AND imported (globals.css) but unused —
   standardize on it for enter/exit; per-word CSS reveal for streamed text (Streamdown technique,
   in-house, no lib); `@number-flow/react` for KPI odometers (reduced-motion-safe, tabular-nums,
   Intl-driven — pairs with lib/format.ts); ECharts-native entrance stagger; Motion (motion.dev)
   only if/when CSS can't (LazyMotion pattern, never the full 34kb component); View Transitions
   still experimental in Next 16 — skip.

## The audit in one line

Three design systems coexist on one good token spine; the fix is finishing the middle one
(`components/ui` on Base UI + tokens-v2) and draining the other two into it.

## Wave 1 — One system (coherence; audit's ten ordered moves)

1. Fix undefined-token fallthroughs (ClarifyGateCard `--panel/--panel2`→`--bg-2/--bg-3`;
   ApprovalModal `--amber*`→`--amb*`).
2. Tokenize chat hexes: user bubble `#633D96/#05355D`, tables-used chip `#1e2d3d`, composer's
   retired-v1-blue focus glow → v2 tokens (`--bfocus`/`--acc-dim`).
3. Cap the chat measure (`max-w` on the message column; charts/tables keep the full column).
4. Revive the dead `dark:` variant (custom-variant bound to `[data-theme="dark"]`).
5. Re-point the shadcn bridge (`--radius`→`var(--r1)`), complete the semantic-var set.
6. Crown StatusChip as the ONE chip vocabulary (fold TrustReceipt's private Badge et al.).
7. Add missing primitives via the shadcn CLI (dialog/input/textarea/select/tooltip/tabs, Base UI
   backend) and convert the three simplest hand-rolled modals as the proof pattern.
8. Sync AugTable's light antd theme to tokens-v2 (and derive both antd theme objects from computed
   tokens so the duplication can't drift).
9. Icons: converge on lucide (shadcn ecosystem default; harvested components arrive with it);
   migrate the chat surface first, replace unicode glyph "icons" (deferred to Wave 2 where it
   overlaps the chat rework).
10. Ratchet raw `<button>` down through the chat surface (ChatMessage/ChatPanel) and QueryBuilder;
    lower the lint:elements baseline with each conversion.

## Wave 2 — CopilotKit-grade chat surface — SHIPPED

- **Composer pill** — soft `--r-composer` (22px) corner, surface one step up from the page,
  shadow-only elevation, whisper border until the focus ring lights the v2 accent.
- **Send ⇄ Stop morph** — one solid circular button in place: filled interactive-blue disc with an
  up-arrow while composing → filled square while streaming (Stop always one click away).
- **Streaming caret + stream-in** — a pulsing round `.aug-caret` trails the live narrative and
  vanishes when the terminal `insight` lands; the prose block settles in once with `.aug-stream-in`
  (blur-lift, applied to the container so per-delta markdown re-renders don't re-trigger it). Rides
  the CK-0.2 `insight_delta` stream. Both reduced-motion-gated.
- **User bubble** — softened to the `--r3` (12px) corner; assistant answers stay full-width prose
  (no bubble) — the CK asymmetry the app already had.
- **Hover toolbar + copy-confirm** — a `Copy` action that stays invisible until the turn is hovered
  and never appears mid-stream; copies headline + narrative with an in-place green-tick (`aug-check-pop`),
  no toast, no layout shift.
- **Floating scroll-to-bottom** — the "Jump to latest" affordance (landed in Wave 1) over the
  stick-to-bottom hook, shown only when the user scrolls up off the newest content.
- **Motion** — no new dependency: the app's own `aug-anim-*` / `aug-*` vocabulary (already
  reduced-motion-gated) is the standard; Wave 2 extends it with `aug-caret` / `aug-stream-in`.
  `tw-animate-css` remains imported and available for future harvested components.

**Deferred — `@number-flow/react` KPI odometers.** The chat-surface `BriefMetrics` renders
already-formatted strings (`€177`, `57.8%`, `$3.00 avg/record`) — retrofitting an odometer there
would mean parsing numerics back out of display strings (fragile). The clean target is the briefing
**scorecard** (`IndustryKpiStrip`, which keeps `raw: Number(cell)`), but it adds an npm dependency
and lives off the chat surface — moved to Wave 3 so Wave 2 stays dependency-free (no `npm ci` risk,
no bundle bloat). Code-block furnishing (`SqlBlock`) was already card-like (framed `--code-bg` +
hover copy) — left as-is.

## Wave 3 — harvest expansion — SHIPPED (first slice)

- **NumberFlow KPI odometers** (`@number-flow/react@0.6.1`, exact-pinned, strict-`npm ci`-verified)
  on the briefing scorecard: values roll odometer-style on change and on first paint. Rendering is
  **byte-identical** to the legacy strings (pre-rounded values + fixed fraction digits + pinned
  en-US locale — proven over a 1.24M-value replay harness, 0 mismatches), and the GroundedNumber
  receipt affordance is fully preserved (it stays the in-flow layout/click layer; the odometer
  paints over it aria-hidden — the card cannot shift while digits roll). Reduced-motion respected
  by NumberFlow's default. Any future `formatMetric` branch must pre-round the same way or omit
  `flow` to fall back to plain text.
- **ThinkingTrace + TrustReceipt polish**: every unicode glyph (`PURPOSE_ICON` map, `◆ ⚡ ▸ ▾ ✓ ⚠
  ✎ ✦ ▤`) replaced with @atlaskit/icon core icons (badge wording untouched — the "resolved
  reading" signal keeps its exact text); the CK smooth-disclosure pattern landed as one
  `.aug-disclose` utility (grid-template-rows 0fr→1fr, reduced-motion-gated) on the trace's
  streamed-substeps region and the Trust Receipt's expanded panel — open/close animates height
  instead of snapping; restored turns never animate on mount.
- **Ratchet paydown**: all 91 raw `<button>`s in the four hotspots (QueryBuilder 45, CatalogScreen
  18, MonitorsPanel 14, AddDataPanel 14) converted to `<Button>` with pixel-preserving overrides;
  baseline **183 → 92**.

### Wave 3 remainder (queued)

prompt-kit reasoning/chain-of-thought/tool/source cards for the deep path; AI Elements
inline-citation/context-meter; shadcn chat primitives (MessageScroller/Bubble) as they stabilize;
icon convergence (lucide-vs-atlaskit decision — Wave 3 deliberately stayed on atlaskit, the chat
surface's dominant set); the remaining ~92 raw buttons (next hotspots: app/page.tsx 20,
ActivityLog 10, OntologyPanel 9); antd table replacement decision — evidence-gated.

## Rules for every copy-in

Harvested files are repo code: they pass lint:tokens (no raw radii/px sizes — new radii become
tokens), lint:elements (no raw buttons), lint:format (numbers/dates through lib/format.ts), get
re-seated on `@base-ui/react` where they assume Radix, and strip AI-SDK type imports in favor of
our `ChatTurn` shapes. `@import` lines stay bare (Tailwind v4 gotcha). Motion is
reduced-motion-gated; restored turns (`startedAt===0`) stay inert.
