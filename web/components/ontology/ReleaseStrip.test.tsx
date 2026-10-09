// @vitest-environment jsdom
/**
 * Arc OC-2 — the release strip: nothing while releases are off; with them on, which release everyone reads, each
 * waiting change with its class and what it touches, Publish refused while a change would break something, and a
 * discard of one change sent with its kind and id.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReleaseStrip } from "./ReleaseStrip";

type Call = { url: string; method: string };

function serve(state: unknown) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), method: init?.method ?? "GET" });
    if (String(url).includes("/ontology/release/discard")) return new Response(JSON.stringify({ discarded: 1 }));
    if (String(url).includes("/ontology/release/publish")) {
      return new Response(JSON.stringify({ number: 3, id: "c/s@3", restated_claims: ["a1"] }));
    }
    return new Response(JSON.stringify(state));
  }));
  return calls;
}

const meaning = {
  element: "ontology:c/s/process/fulfilment", kind: "process", target_id: "fulfilment", change: "changed",
  class: "MEANING", reasons: [{ class: "MEANING", why: "the promise 'delivery' changed: within_days 5 → 7" }],
  fields: ["changed stages[2].promise.within_days"], by: "ana",
  touches: { claims: [{ id: "a1", key: "claim:x", text: "late deliveries were 12%", definition_version: "c/s@2" }],
             cards: [], automations: [{ id: "u1", name: "Delivery watch", how: "its trigger watches the process" }] },
};
const breaking = { ...meaning, element: "ontology:c/s/entity/Review", kind: "entity", target_id: "Review",
  change: "withdrawn", class: "ERR", reasons: [{ class: "ERR", why: "it is withdrawn, and 1 thing relies on it" }],
  touches: { claims: [], cards: [], automations: [] } };

function state(draft: unknown[], enabled = true) {
  return { enabled, connection_id: "c", schema_name: "s", releases: [],
           published: { number: 2, id: "c/s@2", at: "2026-10-09T08:41:25+00:00", by: "ana", note: "", elements: 4 },
           draft };
}

afterEach(() => vi.unstubAllGlobals());

describe("ReleaseStrip", () => {
  it("renders nothing while releases are off", async () => {
    const calls = serve(state([], false));
    const { container } = render(<ReleaseStrip connectionId="c" schema="s" onChanged={() => {}} />);
    await waitFor(() => expect(calls.length).toBe(1));
    expect(container.firstChild).toBeNull();
  });

  it("says which release everyone reads and what each change touches", async () => {
    serve(state([meaning]));
    render(<ReleaseStrip connectionId="c" schema="s" onChanged={() => {}} />);
    expect(await screen.findByText(/1 change waiting to be published/)).toBeTruthy();
    expect(screen.getByText(/still read release 2/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Review the changes" }));
    expect(screen.getByText("changes a meaning")).toBeTruthy();
    expect(screen.getByText(/within_days 5 → 7/)).toBeTruthy();
    expect(screen.getByText(/Touches 1 claim · 1 automation: Delivery watch/)).toBeTruthy();
    expect(screen.getByText(/publishing restates the claims/)).toBeTruthy();
  });

  it("refuses to publish while a change would break something, and discards one change by its id", async () => {
    const calls = serve(state([breaking, meaning]));
    const changed = vi.fn();
    render(<ReleaseStrip connectionId="c" schema="s" onChanged={changed} />);
    const publish = await screen.findByRole("button", { name: "Publish" });
    expect((publish as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Review the changes" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Discard" })[0]);
    await waitFor(() => expect(changed).toHaveBeenCalled());
    const discard = calls.find(c => c.url.includes("/ontology/release/discard"));
    expect(discard?.method).toBe("POST");
    expect(discard?.url).toContain("kind=entity");
    expect(discard?.url).toContain("target_id=Review");
  });

  it("publishes and says how many claims were restated", async () => {
    const calls = serve(state([meaning]));
    render(<ReleaseStrip connectionId="c" schema="s" onChanged={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Publish" }));
    expect(await screen.findByText("Published release 3 — 1 claim restated")).toBeTruthy();
    expect(calls.some(c => c.url.includes("/ontology/release/publish") && c.method === "POST")).toBe(true);
  });
});
