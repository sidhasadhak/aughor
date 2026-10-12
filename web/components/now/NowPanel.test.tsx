// @vitest-environment jsdom
/**
 * Now, laid out to CLARITY: four figures first, what waits on a person in amber with its buttons on the row, the
 * same send to the same place folded into one row with its count, corrections folded by kind with the re-issued
 * ones counted rather than dropped, and the Briefing read from the shape the API serves.
 *
 * Every read goes through `fetch`, which is answered here — nothing reaches the live API from jsdom.
 */
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { forgetMe } from "@/lib/useMe";
import { keptBriefing, NowPanel, type NowDoors } from "./NowPanel";

const WEEK = "2026-10-05";

const departure = (over: Record<string, unknown>) => ({
  id: "d", ts: "2026-10-11T09:03:00Z", org_id: "default", kind: "slack_post", state: "departed", conn_id: "c1",
  automation_id: "a1", automation_name: "The Look - Daily Briefing", actor: "", target: "sb_1:#ask_aughor", addressed_to: "",
  reasons: [], checks: { triage: "mission 0.00 · size 0.00 · waiting 0.50 · novelty 1.00 → score 0.30" }, guards: {},
  receipt: {}, question: {}, text_preview: "TheLook generated $21,414.64 in revenue on October 3.",
  source_kind: "automation", source_id: "a1", origin: "unattended", about: "", as_of: "", verdict: "", verdict_note: "",
  verdict_at: "", answer: "", answered_by: "", answered_at: "", ...over,
});

let routes: Record<string, unknown>;

function answer(url: string): unknown {
  const u = new URL(url, "http://x");
  const p = u.pathname;
  if (p === "/departures") return u.searchParams.get("awaiting") ? { departures: [] } : routes.departures;
  if (p === "/attention/held") return { week_start: WEEK, held: routes.held ?? [] };
  if (p === "/attention/budget") return { addressee: u.searchParams.get("addressee"), week_start: WEEK, slots: 10, used: 2, left: 8, held: [], held_count: 0, note: "" };
  if (p === "/record/decisions") return routes.decisions;
  if (p === "/record/inquiries" || p === "/record/missions") return [];
  if (p.endsWith("/needs-human")) return { count: 0, sources: {}, rows: [] };
  if (p === "/record/set-aside") return { today: "2026-10-12", active: [], returned: [] };
  if (p === "/record/corrections") return routes.corrections;
  if (p === "/briefing/organisation") return routes.briefing;
  if (p === "/rbac/me") return { user_id: null, actor: "amit", signed_in: false, org_id: "default", roles: [], permissions: [] };
  return {};
}

globalThis.fetch = (async (input: RequestInfo | URL) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  return new Response(JSON.stringify(answer(url)), { status: 200, headers: { "Content-Type": "application/json" } });
}) as typeof fetch;

const doors = new Proxy({}, { get: () => () => {} }) as NowDoors;
const connections = [{ id: "c1", name: "theLook", builtin: false }] as never;
const mount = () => render(<NowPanel connections={connections} contextReady doors={doors} />);

const now = new Date().toISOString();

beforeEach(() => {
  forgetMe();
  try { localStorage.clear(); } catch { /* none */ }
  routes = {
    departures: { departures: [
      departure({ id: "s1", ts: "2026-10-11T09:03:00Z" }),
      departure({ id: "s2", ts: "2026-10-10T09:03:00Z", text_preview: "TheLook generated $19,087.76 in revenue." }),
      departure({ id: "s3", ts: "2026-10-08T07:01:00Z", kind: "briefing", target: "", automation_name: "theLook — Day Briefing",
        checks: {}, text_preview: "# Daily Briefing — 2026-09-09" }),
      departure({ id: "old", ts: "2026-09-30T09:00:00Z" }),
    ] },
    decisions: [{ id: "dec1", key: "k1", chosen: "Pause the promotion feed", review_on: "2026-10-12", decided_by: "user:amit" }],
    corrections: {
      counts: {}, note: "",
      labels: { prediction_outside_interval: "a prediction whose actual fell outside its band", restatement: "a number we gave later changed" },
      entries: [
        { kind: "prediction_outside_interval", at: now, connection_id: "c1", ref: "r1", why: "",
          believed: "expected: Revenue $11,330 to $14,131 for 2026-09-10 (its own past)", replaced_by: "the actual was 14142.289977550507: above the band" },
        { kind: "prediction_outside_interval", at: now, connection_id: "c1", ref: "r2", why: "",
          believed: "expected: Units Sold 229.34 to 280.66 for 2026-09-10 (its own past)", replaced_by: "the actual was 296.0: above the band" },
        { kind: "restatement", at: now, connection_id: "c1", ref: "r1", why: "restated",
          believed: "expected: Revenue $11,330 to $14,131", replaced_by: "expected: Revenue $11,330 to $14,131" },
      ],
    },
    // The shape the API serves: a kept Briefing's fields on the row itself, `briefing: null` on one with none.
    briefing: { connections: 2, with_briefing: 1, briefings: [
      { connection_id: "c1", connection_name: "theLook", as_of: "2026-10-11", headline_theme: "Inventory Sell-Through Rate Surges",
        lede: "On Saturday the Inventory Sell-Through Rate rose to 59.2%." },
      { connection_id: "c2", connection_name: "DuckDB", briefing: null, note: "no Briefing kept for this connection yet" },
    ] },
  };
});

describe("Now", () => {
  it("opens on four figures — sent, waiting, held, corrected — each with one muted line", async () => {
    mount();
    const figures = await screen.findByTestId("now-figures");
    await within(figures).findByText("2 of 10 slots used");
    expect(within(figures).getByTestId("now-fig-sent-value")).toHaveTextContent("3");
    expect(within(figures).getByTestId("now-fig-waiting-value")).toHaveTextContent("1");
    expect(within(figures).getByTestId("now-fig-waiting")).toHaveTextContent("1 review");
    expect(within(figures).getByTestId("now-fig-held-value")).toHaveTextContent("0");
    // two changed what you were told; the one re-issued with the same words is not counted as a correction
    expect(within(figures).getByTestId("now-fig-corrected-value")).toHaveTextContent("2");
  });

  it("puts what waits on a person in amber, with its buttons on its row", async () => {
    mount();
    const needs = await screen.findByTestId("now-needs");
    await within(needs).findByText(/What became of “Pause the promotion feed”\?/);
    expect(needs).toHaveAttribute("data-waiting", "true");
    expect(within(needs).getByRole("button", { name: "Open the decision" })).toBeInTheDocument();
    expect(within(needs).getByRole("button", { name: "Not now" })).toBeInTheDocument();
  });

  it("is one muted line on a plain card when nothing waits", async () => {
    routes.decisions = [];
    mount();
    const needs = await screen.findByTestId("now-needs");
    await within(needs).findByText("Nothing waits on you.");
    expect(needs).toHaveAttribute("data-waiting", "false");
  });

  it("folds the same send to the same place into one row with its count, and says a send that used no slot", async () => {
    mount();
    const groups = await screen.findAllByTestId("now-send-group");
    expect(groups).toHaveLength(2);
    expect(groups[0]).toHaveTextContent("The Look - Daily Briefing");
    expect(groups[0]).toHaveTextContent("→ #ask_aughor");
    expect(groups[0]).toHaveTextContent("×2");
    expect(groups[0]).toHaveTextContent("ranked on its novelty, the cost of waiting — score 0.30");
    expect(groups[1]).toHaveTextContent("no place · used no slot");
    // last week's send is not this week's: two of the three Daily Briefing sends were this week
    expect(groups[0]).not.toHaveTextContent("×3");
  });

  it("gives what was held a card only when something was — its figure already says none", async () => {
    mount();
    await screen.findAllByTestId("now-send-group");
    expect(screen.getByTestId("now-fig-held")).toHaveTextContent("nothing lost a slot");
    expect(screen.queryByTestId("now-held")).toBeNull();
    routes.held = [{ departure_id: "h1", at: now, kind: "slack_post", target: "sb_1:#ask_aughor", addressed_to: "", by: "Daily Briefing",
      text: "Revenue fell 3%", why: "the week's slots were spent", triage: "novelty 1.00 → score 0.20" }];
    mount();
    const held = await screen.findByTestId("now-held");
    expect(within(held).getByTestId("now-held-row")).toHaveTextContent("ranked on its novelty — score 0.20");
  });

  it("folds corrections by kind and counts the ones re-issued with the same words instead of dropping them", async () => {
    mount();
    const kinds = await screen.findAllByTestId("now-correction-kind");
    expect(kinds).toHaveLength(1);
    expect(kinds[0]).toHaveTextContent("a prediction whose actual fell outside its band");
    expect(kinds[0]).toHaveTextContent("Revenue");
    expect(kinds[0]).toHaveTextContent("Units Sold");
    expect(kinds[0]).toHaveTextContent("2");
    expect(screen.getByTestId("now-restated")).toHaveTextContent("1 more was re-issued with the same words");
  });

  it("reads a kept Briefing from the row the API serves — not 'no Briefing kept' over one that is", async () => {
    mount();
    const rows = await screen.findAllByTestId("now-briefing-row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Inventory Sell-Through Rate Surges");
    expect(rows[0]).toHaveTextContent("theLook · as of Sun 11 Oct");
    expect(screen.getByTestId("now-briefing")).toHaveTextContent("1 connection has no Briefing kept yet");
    expect(screen.queryByText(/No Briefing kept yet for any/)).toBeNull();
  });
});

describe("keptBriefing", () => {
  it("reads both shapes, and a row with none as none", () => {
    expect(keptBriefing({ connection_id: "a", connection_name: "A", as_of: "2026-10-11", headline_theme: "Up", lede: "x" }))
      .toEqual({ as_of: "2026-10-11", headline: "Up", lede: "x" });
    expect(keptBriefing({ connection_id: "a", connection_name: "A", briefing: { as_of: "2026-10-01", headline: "Old", lede: "y" } }))
      .toEqual({ as_of: "2026-10-01", headline: "Old", lede: "y" });
    expect(keptBriefing({ connection_id: "a", connection_name: "A", briefing: null })).toBeNull();
    expect(keptBriefing({ connection_id: "a", connection_name: "A" })).toBeNull();
  });
});
