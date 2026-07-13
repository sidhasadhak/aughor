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

## Wave 2 — CopilotKit-grade chat surface

Composer pill + two-state grid + send⇄stop morph; bubble asymmetry + turn rhythm; hover
toolbars + copy-confirm; streaming dot cursor + per-word reveal riding the CK-0.2 `insight_delta`
stream; code-block cards; floating scroll-to-bottom over the existing stick-to-bottom hook;
`@number-flow/react` on Brief KPis; tw-animate-css standardization + a global reduced-motion
override.

## Wave 3 (later) — harvest expansion

prompt-kit reasoning/chain-of-thought/tool/source cards for the deep path (ThinkingTrace
upgrade); AI Elements inline-citation/context-meter; shadcn chat primitives
(MessageScroller/Bubble) as they stabilize; icon convergence completion; QueryBuilder and the
remaining raw-button hotspots; antd table replacement decision (keep antd 6 vs shadcn Table) —
evidence-gated.

## Rules for every copy-in

Harvested files are repo code: they pass lint:tokens (no raw radii/px sizes — new radii become
tokens), lint:elements (no raw buttons), lint:format (numbers/dates through lib/format.ts), get
re-seated on `@base-ui/react` where they assume Radix, and strip AI-SDK type imports in favor of
our `ChatTurn` shapes. `@import` lines stay bare (Tailwind v4 gotcha). Motion is
reduced-motion-gated; restored turns (`startedAt===0`) stay inert.
