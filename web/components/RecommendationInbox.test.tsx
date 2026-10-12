// @vitest-environment jsdom
/**
 * The Inbox, laid out to CLARITY: the recommendations a report keeps — in either shape it may keep them — read
 * into four figures, the reviews that came due with their answer on the row, where they stand as a funnel, and
 * the list. A read that failed says so; an analysis that could not be read is counted, never skipped in silence.
 *
 * Every read goes through `fetch`, answered here — nothing reaches the live API from jsdom.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { beforeEach, describe, expect, it } from "vitest";

import { readRecs, RecommendationInbox } from "./RecommendationInbox";

/** The wire's own path for a deep analysis (its frozen internal name). */
const RUNS = "/investigations";
const SCHEDULED = "[Scheduled-run context — written by code, not inferred]\nThis is a scheduled daily run.\n\nWhat changed in theLook?";

let list: unknown;
let details: Record<string, unknown>;
let outcomes: Record<string, unknown[]>;
const posted: { url: string; body: unknown }[] = [];

globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  const p = new URL(url, "http://x").pathname;
  const json = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status, headers: { "Content-Type": "application/json" } });
  if (init?.method === "POST") {
    const body = JSON.parse(String(init.body));
    posted.push({ url: p, body });
    const [, , id, , index] = p.split("/");
    return json({ id: `${id}_rec_${index}`, inv_id: id, rec_index: Number(index), rec_text: body.rec_text, status: body.status,
      metric_name: null, metric_before: null, metric_after: null, created_at: "", updated_at: "" });
  }
  if (p === RUNS) return list instanceof Error ? json({ detail: "down" }, 503) : json(list);
  const m = p.match(/^\/[a-z]+\/([^/]+)(\/outcomes)?$/);
  if (m && m[2]) return json(outcomes[m[1]] ?? []);
  if (m) return m[1] in details ? json(details[m[1]]) : json({ detail: "gone" }, 500);
  return json({});
}) as typeof fetch;

const run = (id: string, over: Record<string, unknown> = {}) => ({
  id, question: "Why did revenue move?", headline: `Headline of ${id}`, status: "complete", kind: "investigation",
  started_at: "2026-10-10T09:00:00Z", completed_at: "2026-10-10T09:03:00Z", ...over,
});

const mount = () => render(<Theme><RecommendationInbox onOpenInvestigation={() => {}} workspaceId="default" /></Theme>);

beforeEach(() => {
  posted.length = 0;
  list = [run("a", { question: SCHEDULED, headline: "Revenue rose 11.9% on October 3", completed_at: "2026-10-11T09:03:00Z" }),
    run("b"), run("c"), run("chat1", { kind: "chat" })];
  details = {
    // the shape every stored report holds: objects under `recommendations`
    a: { report: { recommendations: [
      { action: "Monitor daily revenue for the next 7 days.", expected_impact: "N/A", owner: "Operations Team", timeline: "2026-10-18" },
      { action: "Audit the Search campaign logs.", expected_impact: "Isolate the lever.", owner: "Marketing Analytics", timeline: "Next 7 days" },
    ] } },
    // an older or hand-built report: plain strings under `recommended_actions`
    b: { report: { recommended_actions: ["Re-check the delivery promise."] } },
  };
  outcomes = { b: [{ id: "b_rec_0", inv_id: "b", rec_index: 0, rec_text: "Re-check the delivery promise.", status: "accepted",
    metric_name: null, metric_before: null, metric_after: null, created_at: "", updated_at: "",
    review_question: "Did the late deliveries fall below 8%?", review_asked_to: "ops@thelook" }] };
});

describe("the Inbox", () => {
  it("reads the recommendations a report keeps in either shape, into four figures", async () => {
    mount();
    const figures = await screen.findByTestId("inbox-figures");
    expect(within(figures).getByTestId("inbox-fig-open-value")).toHaveTextContent("3");
    expect(within(figures).getByTestId("inbox-fig-open")).toHaveTextContent("from 2 deep analyses");
    expect(within(figures).getByTestId("inbox-fig-open")).toHaveTextContent("newest 20 read");
    expect(within(figures).getByTestId("inbox-fig-progress-value")).toHaveTextContent("1");
    expect(within(figures).getByTestId("inbox-fig-verified-value")).toHaveTextContent("0");
    const rows = screen.getAllByTestId("inbox-rec");
    expect(rows.map(r => r.textContent)).toEqual([
      expect.stringContaining("Monitor daily revenue for the next 7 days."),
      expect.stringContaining("Audit the Search campaign logs."),
      expect.stringContaining("Re-check the delivery promise."),
    ]);
    // the analysis it came from is named by its headline — the scheduled run's plumbing never reaches the page
    expect(rows[0]).toHaveTextContent("Operations Team");
    expect(rows[0]).toHaveTextContent(/from\s*Revenue rose 11.9% on October 3/);
    expect(screen.queryByText(/Scheduled-run context/)).toBeNull();
  });

  it("says an analysis it could not read, instead of skipping it", async () => {
    mount();
    expect(await screen.findByText("1 deep analysis could not be read")).toBeInTheDocument();
  });

  it("says a failed read with a Retry, never the empty line", async () => {
    list = new Error("down");
    mount();
    expect(await screen.findByText(/Could not read the recommendations/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText(/No recommendation in the newest/)).toBeNull();
  });

  it("puts a review that came due under Needs you, answered on its row", async () => {
    mount();
    const needs = await screen.findByTestId("inbox-needs");
    await within(needs).findByText(/Did the late deliveries fall below 8%\?/);
    expect(needs).toHaveAttribute("data-waiting", "true");
    fireEvent.click(within(needs).getByRole("button", { name: "Verified" }));
    await within(needs).findByText("No review has come due.");
    expect(posted).toEqual([{ url: `${RUNS}/b/recommendations/0/outcome`,
      body: { rec_text: "Re-check the delivery promise.", status: "verified" } }]);
    expect(screen.getByTestId("inbox-fig-verified-value")).toHaveTextContent("1");
    expect(screen.getByTestId("inbox-fig-open-value")).toHaveTextContent("2");
  });

  it("draws where they stand as a funnel: how many reached at least each stage", async () => {
    mount();
    const funnel = await screen.findByTestId("inbox-funnel");
    expect(funnel).toHaveTextContent(/Proposed\s*3/);
    expect(funnel).toHaveTextContent(/Accepted\s*1/);
    expect(funnel).toHaveTextContent(/Verified\s*0/);
  });
});

describe("readRecs", () => {
  it("reads objects and strings in the report's order, drops an empty one and an N/A impact", () => {
    expect(readRecs({ recommendations: [{ action: "Do A", expected_impact: "N/A", owner: "Ops", timeline: "2026-10-18" }, { action: "" }] }))
      .toEqual([{ action: "Do A", impact: "", owner: "Ops", timeline: "2026-10-18" }]);
    expect(readRecs({ recommended_actions: ["Do B"] })).toEqual([{ action: "Do B", impact: "", owner: "", timeline: "" }]);
    expect(readRecs(null)).toEqual([]);
  });
});
