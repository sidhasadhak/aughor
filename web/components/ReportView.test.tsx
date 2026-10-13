// @vitest-environment jsdom
/**
 * A report's recommended actions, and where they stand. A read of their outcomes that failed used to come back as
 * an empty list — the client turned a refused response into `[]` and the report swallowed the rest — so every
 * recommendation read as never marked. A failed read is now said under them; a genuine empty list stays as it was.
 *
 * `fetch` is answered here, so the real client helper runs and nothing reaches the live API from jsdom.
 */
import { fireEvent, render, screen } from "@/lib/testing";
import { beforeEach, describe, expect, it } from "vitest";

import { ReportView } from "@/components/ReportView";
import type { Report } from "@/lib/types";

let outcomesStatus = 200;

globalThis.fetch = (async (input: RequestInfo | URL) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  const json = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status, headers: { "Content-Type": "application/json" } });
  if (new URL(url, "http://x").pathname.endsWith("/outcomes")) {
    return outcomesStatus === 200 ? json([]) : json({ detail: "the store is locked" }, outcomesStatus);
  }
  throw new Error(`unexpected fetch ${url}`);
}) as typeof fetch;

const report: Report = {
  headline: "Late deliveries rose", verdict: "The carrier change moved the promise.", key_findings: [],
  what_is_not_the_cause: [], data_quality_notes: [], risks: [], recommended_actions: ["Re-check the delivery promise."],
};

const open = async () => {
  render(<ReportView report={report} queryCount={0} invId="r1" />);
  fireEvent.click(screen.getByRole("button", { name: /Recommended Actions/ }));
  return screen.findByText("Re-check the delivery promise.");
};

beforeEach(() => { outcomesStatus = 200; });

describe("where the recommendations stand", () => {
  it("says a failed read under them, with a Retry", async () => {
    outcomesStatus = 503;
    await open();
    expect(await screen.findByText(/Could not read where these stand — the store is locked/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("says nothing extra when the read answers with no outcomes", async () => {
    await open();
    expect(screen.getByRole("button", { name: "Mark" })).toBeInTheDocument();
    await new Promise(r => setTimeout(r, 0));
    expect(screen.queryByText(/Could not read/)).toBeNull();
  });
});
