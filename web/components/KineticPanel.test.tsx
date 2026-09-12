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
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { KineticPanel } from "@/components/KineticPanel";

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

describe("KineticPanel — declaring an action about an object", () => {
  it("sends an object parameter and the edit it writes, not just the value params", async () => {
    const user = userEvent.setup();
    render(<KineticPanel connectionId="c1" />);

    await user.type(screen.getByPlaceholderText("action id (e.g. refund_order)"), "flag_order_for_review");
    await user.selectOptions(screen.getAllByRole("combobox")[0], "annotate");
    await user.type(screen.getByPlaceholderText(/object type this action is about/), "order");

    // The first parameter row becomes the object the action is about.
    await user.clear(screen.getByPlaceholderText("name (e.g. amount_eur)"));
    await user.type(screen.getByPlaceholderText("name (e.g. amount_eur)"), "order");
    await user.selectOptions(screen.getByDisplayValue("value"), "object");
    await user.type(screen.getByPlaceholderText("object type (e.g. order)"), "order");

    await user.click(screen.getByRole("button", { name: "+ Add an edit" }));
    await user.type(screen.getByPlaceholderText("object param (e.g. order)"), "order");
    await user.type(screen.getByPlaceholderText("property (e.g. review_flag)"), "review_flag");
    await user.type(screen.getByPlaceholderText(/note — /), "duplicate charge");

    await user.click(screen.getByRole("button", { name: "Save action" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.url).toContain("/ontology/kinetic-actions/flag_order_for_review");
    expect(put.body.object_type).toBe("order");
    expect(put.body.params).toEqual([{ name: "order", kind: "object", object_type: "order", required: true }]);
    expect(put.body.edits).toEqual([
      { object: "order", property: "review_flag", value: "true", note: "duplicate charge" }]);
  });

  it("keeps a plain value parameter typed, with no object_type smuggled in", async () => {
    const user = userEvent.setup();
    render(<KineticPanel connectionId="c1" />);
    await user.type(screen.getByPlaceholderText("action id (e.g. refund_order)"), "refund_order");
    await user.click(screen.getByRole("button", { name: "Save action" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")!.body.params).toEqual([
      { name: "amount_eur", data_type: "NUMERIC", required: true }]);
  });
});

describe("KineticPanel — withdrawing one overlay edit", () => {
  it("deletes THAT edit on THIS connection and re-reads the list", async () => {
    annotations = [{ id: "e1", table: "orders", column: "status", key_column: "order_id", row_key: "8821",
                     body: "known test order", source: "user" }];
    const user = userEvent.setup();
    render(<KineticPanel connectionId="c1" />);
    await user.click(screen.getByRole("button", { name: "Annotations" }));

    await screen.findByText("known test order");
    await user.click(screen.getByRole("button", { name: "Withdraw" }));

    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    const gone = calls.find((c) => c.method === "DELETE")!;
    expect(gone.url).toContain("/kinetic-actions/annotations/e1");
    expect(gone.url).toContain("connection_id=c1");
    await waitFor(() => expect(screen.queryByText("known test order")).toBeNull());
  });
});
