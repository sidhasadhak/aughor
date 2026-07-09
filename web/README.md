# Aughor — web

The Next.js frontend for [Aughor](../README.md). It talks to the FastAPI backend
on `:8000` and streams investigations over Server-Sent Events.

## Running

From the **repository root** (this starts the API and the web app together):

```bash
./start.sh
```

To run only the frontend against an API you already have running:

```bash
npm install
npm run dev          # http://localhost:3000
```

## Stack

- **Next.js 16** (App Router) + **React 19**, TypeScript in `strict` mode
- **Tailwind CSS v4**, with a token layer in `styles/tokens.css`
- **ECharts** and **Observable Plot** for exhibits
- **DM Sans** (SIL OFL 1.1) loaded via `next/font/local` — see [`../NOTICE`](../NOTICE)

## Layout

| Path | What lives there |
|---|---|
| `app/` | App Router entry — a single client page that mounts the workspace |
| `components/` | Panels and cards; `components/ui/` holds the primitives |
| `lib/` | API client, hooks, formatting, and domain types |
| `lib/api.gen.ts` | **Generated — do not edit by hand.** See below |
| `styles/` | Design tokens and the typography scale |
| `scripts/` | The three lint gates that CI runs |

## The generated API client

`lib/api.gen.ts` is produced from the backend's live FastAPI route surface. After
changing a route or a Pydantic model, regenerate it:

```bash
npm run gen:api
```

CI fails if the committed file drifts from what the backend would generate.

## Checks CI runs

```bash
npx tsc --noEmit      # typecheck (strict)
npm run lint:tokens   # no raw border-radius / pixel font-size — use tokens
npm run lint:format   # numbers and dates render through lib/format.ts
npm run lint:elements # one-way ratchet: the raw <button> count may only shrink
```

There is currently **no frontend test runner**. Typecheck plus the three gates
above are the whole frontend safety net — see [`../CONTRIBUTING.md`](../CONTRIBUTING.md).
