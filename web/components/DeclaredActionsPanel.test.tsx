// @vitest-environment jsdom

/**
 * ON-4's authoring gap, and the withdrawal door.
 *
 * The panel LISTED an action's object parameters and the properties it writes, and could declare neither:
 * `flag_order_for_review` had to be PUT by hand. And an overlay edit could be written from here but never
 * taken back — the only door was the connection-wide purge.
 *
 * These assert on the REQUEST the form makes, because that is the whole claim: a `kind: "object"` parameter
 * carrying its `object_type`, and an `edits` entry naming the param and the property. A form that renders
 * the fields and drops them from the body looks identical on screen.
 */
import { describe, expect, it, beforeEach } from "vitest";
import { render, screen, waitFor } from "@/lib/testing";
import userEvent from "@testing-library/user-event";

import { DeclaredActionsPanel } from "@/components/DeclaredActionsPanel";

type Call = { url: string; method: string; body: any };
const calls: Call[] = [];
let annotations: any[] = [];

function jsonResponse(body: unknown) {
  return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) } as Response;
}

beforeEach(() => {
  calls.length = 0;
  annotations = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url.includes("/ontology/kinetic-actions")) return jsonResponse({});
    if (url.includes("/kinetic-actions/annotations")) {
      if (method === "DELETE") {
        annotations = [];
        return jsonResponse({ withdrawn: "e1", target: "orders.status#order_id=8821" });
      }
      return jsonResponse({ edits: annotations });
    }
    return jsonResponse({});
  }) as typeof fetch;
});

describe("DeclaredActionsPanel — declaring an action", () => {
  // The walk-through of 2026-10-09 found the declare form here pre-filled with a refund rule (`amount_eur`, a EUR 10,000
  // criterion, a body summarising it) that a person saved unless they noticed. The form is gone: "New action" opens the
  // action designer, whose requests are held in `ontology/ActionDesigner.test.tsx` and `lib/actionDraft.test.ts`.
  it("opens the action designer, with nothing of anyone else's rule filled in", async () => {
    const user = userEvent.setup();
    render(<DeclaredActionsPanel connectionId="c1" />);
    expect(screen.queryByTestId("action-designer")).toBeNull();
    await user.click(screen.getByTestId("actions-new"));
    const page = await screen.findByTestId("action-designer");
    expect(page.textContent).not.toMatch(/amount_eur|refund|10,?000/i);
    // Only the designer's own defaults: a reason is asked for, and a mark reads "yes".
    expect([...page.querySelectorAll("input, textarea")].map(e => (e as HTMLInputElement).value).filter(Boolean))
      .toEqual(["yes", "Reason"]);
    expect(calls.some(c => c.method !== "GET")).toBe(false);                     // opening it writes nothing
  });
});

describe("DeclaredActionsPanel — withdrawing one overlay edit", () => {
  it("deletes THAT edit on THIS connection and re-reads the list", async () => {
    annotations = [{ id: "e1", table: "orders", column: "status", key_column: "order_id", row_key: "8821",
                     body: "known test order", source: "user" }];
    const user = userEvent.setup();
    render(<DeclaredActionsPanel connectionId="c1" />);
    // The overlay edits share the page with the declared actions now — no tab to open first.

    await screen.findByText("known test order");
    await user.click(screen.getByRole("button", { name: "Withdraw" }));

    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    const gone = calls.find((c) => c.method === "DELETE")!;
    expect(gone.url).toContain("/kinetic-actions/annotations/e1");
    expect(gone.url).toContain("connection_id=c1");
    await waitFor(() => expect(screen.queryByText("known test order")).toBeNull());
  });
});
