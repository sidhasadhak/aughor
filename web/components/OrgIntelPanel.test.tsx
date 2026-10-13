// @vitest-environment jsdom

/**
 * Org, read as a page: the promoted findings by domain, the connection they came from named once, and the two things
 * an empty page must not hide — a read that failed is a failed read (with Retry), and an empty answer may be a store
 * that could not be read (`GET /org-intelligence` answers [] for both).
 */
import { beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";

import { render, screen, waitFor, within } from "@/lib/testing";
import { OrgIntelPanel } from "@/components/OrgIntelPanel";

let found: unknown[] | "fail" = [];
const calls: { url: string; method: string }[] = [];

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) }) as Response;
const finding = (id: string, domain: string, text: string, at: string) => ({
  id, insight_id: `f${id}`, canvas_id: "conn:c1", connection_id: "c1", schema: "s", text, domain, angle: "retention",
  novelty: 4, promoted_by: "user", promoted_at: at,
});

beforeEach(() => {
  found = [];
  calls.length = 0;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method });
    if (url.includes("/connections")) return ok([{ id: "c1", name: "theLook" }]);
    if (url.includes("/org-intelligence")) {
      if (method === "DELETE") return ok({ ok: true });
      if (found === "fail") return { ok: false, status: 500, json: async () => ({}), text: async () => "" } as Response;
      return ok(found);
    }
    return ok({});
  }) as typeof fetch;
});

describe("OrgIntelPanel", () => {
  it("reads as a page: findings under their domain, the source named once, each removable", async () => {
    found = [
      finding("1", "Customers", "Repeat buyers spend more in their second month.", "2026-10-11T08:00:00Z"),
      finding("2", "Returns", "Outerwear returns run at 3x the average.", "2026-10-09T08:00:00Z"),
      finding("3", "Customers", "Search converts better than Organic.", "2026-10-02T08:00:00Z"),
    ];
    const user = userEvent.setup();
    render(<OrgIntelPanel />);
    const domains = await screen.findAllByTestId("org-domain");
    expect(domains.map(d => d.getAttribute("aria-label"))).toEqual(["Customers", "Returns"]);
    expect(within(domains[0]).getAllByTestId("org-finding")).toHaveLength(2);
    // every finding came from one connection: the sentence names it, no line repeats it, no id shows
    await waitFor(() => expect(screen.getByText(/promoted from theLook's Briefing/)).toBeTruthy());
    expect(document.body.textContent).not.toMatch(/from theLook ·|conn:c1|canvas/);

    await user.click(within(domains[1]).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(calls.some(c => c.method === "DELETE" && c.url.endsWith("/org-intelligence/2"))).toBe(true));
    await waitFor(() => expect(screen.queryByText("Outerwear returns run at 3x the average.")).toBeNull());
  });

  it("says an empty answer may be a store that could not be read", async () => {
    render(<OrgIntelPanel />);
    const empty = await screen.findByTestId("org-empty");
    expect(empty.textContent).toContain("Nothing promoted yet");
    expect(empty.textContent).toContain("or its store could not be read");
  });

  it("shows a failed read as failed, with Retry — never as nothing promoted", async () => {
    found = "fail";
    const user = userEvent.setup();
    render(<OrgIntelPanel />);
    await screen.findByText(/Could not read Org's findings/);
    expect(screen.queryByTestId("org-empty")).toBeNull();
    found = [finding("1", "Customers", "Repeat buyers spend more in their second month.", "2026-10-11T08:00:00Z")];
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Repeat buyers spend more in their second month.")).toBeTruthy();
  });
});
