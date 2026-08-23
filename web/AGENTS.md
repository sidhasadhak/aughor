<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# Tests

`npm test` runs two vitest projects:

- **logic** — `**/*.test.ts` in a `node` environment. Fast (the ~255 pure-function tests
  run in under a second); keep it that way by not reaching for a DOM here.
- **components** — `**/*.test.tsx` in `jsdom`, with `@testing-library/react` and the
  matchers from `@testing-library/jest-dom`. Add `// @vitest-environment jsdom` at the
  top of the file.

**What jsdom cannot do, and why it matters.** It reports every element as 0×0, so any
component that measures itself before drawing will render structure and nothing else.
Measured on `@xyflow/react`: it emits the `react-flow__edges` container and ZERO
`.react-flow__edge` elements regardless of how many edges you pass it. So a test asserting
on rendered edges *cannot fail* — the first draft of `TraceFlow.test.tsx` did exactly that
and stayed green while every edge was suppressed in the component.

For canvases, stub the renderer (partially — `importOriginal`, keep `Handle`/`Position`
real, wrap the stub in the real `ReactFlowProvider`) and assert on **what the component
hands it**. That is where these bugs live: the forest was correct and the canvas got
nothing. Geometry stays a browser question — verify it by driving the browser.

**Before claiming a UI change works**, run all seven gates, not just `npm test`:
`rm -rf .next/dev/types && npx tsc --noEmit`, then `lint:vars`, `lint:tokens`,
`lint:format`, `lint:elements`, `lint:icons`, `lint:palette`. Bare `npm run lint` is not
one of them.
