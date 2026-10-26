// @vitest-environment jsdom
/**
 * Arc FA, FA-1 (flag `objects.find`) — ⌘K finds an object by the name it goes by, across entities.
 *
 * The group is fetched from the server as the reader types — outside the Fuse index, like the Spotlight row — and
 * says what it read: "searched 2 of 5 entities". A hit opens the object's page. With the flag off nothing is
 * fetched, and the palette lists what it always did. The API is mocked: jsdom would reach the live server otherwise.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("@/lib/useAughorChat", () => ({
  useAughorChat: () => ({ messages: [], sendMessage: vi.fn(), status: "ready", error: null }),
}));
vi.mock("@/lib/schema-context", () => ({ useRichSchema: () => ({ schema: null }) }));

const { CommandPalette } = await import("@/components/CommandPalette");

const ANSWER = {
  path: "found", connection_id: "c1", schema_name: "ecommerce", q: "alice smith",
  hits: [{ type: "customer", type_id: "Customer", key: "C00020", title: "Alice Smith", entity_label: "Customer" }],
  searched: 2, of: 5, said: "searched 2 of 5 entities",
  skipped: [{ entity: "order", why: "named by its key (order_id) — there is no name to match" }],
  more: [], withheld: [], withheld_said: [], masked: [],
};

function serve(flagOn: boolean, answer: object = ANSWER) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(String(url));
    if (String(url).includes("/system/flags")) {
      return new Response(JSON.stringify({ "objects.find": { value: flagOn } }), { status: 200 });
    }
    if (String(url).includes("/objects/find")) return new Response(JSON.stringify(answer), { status: 200 });
    return new Response("[]", { status: 200 });
  }));
  return calls;
}

afterEach(() => { vi.unstubAllGlobals(); });

it("finds an object by name, says how many entities it searched, and opens its page", async () => {
  Element.prototype.scrollIntoView = vi.fn();
  const calls = serve(true);
  const onOpenObject = vi.fn();
  const user = userEvent.setup();
  render(<CommandPalette open onClose={vi.fn()} selectedConn="c1" onNavigate={vi.fn()} onGoToChat={vi.fn()}
    onOpenObject={onOpenObject} />);

  await user.type(screen.getByPlaceholderText(/search/i), "alice smith");
  await waitFor(() => expect(screen.getByText("Alice Smith")).toBeTruthy());
  expect(screen.getByText("Objects")).toBeTruthy();
  const said = screen.getByTestId("objects-said");
  expect(said.textContent).toBe("searched 2 of 5 entities");
  expect(said.getAttribute("title")).toContain("order: named by its key");
  const asked = calls.filter(u => u.includes("/objects/find"));
  expect(asked.length).toBeGreaterThan(0);
  expect(asked.every(u => u.includes("connection_id=c1"))).toBe(true);

  await user.click(screen.getByText("Alice Smith"));
  expect(onOpenObject).toHaveBeenCalledWith("/objects/customer/C00020?conn=c1&schema=ecommerce");
});

it("says what it searched when nothing is named so", async () => {
  Element.prototype.scrollIntoView = vi.fn();
  serve(true, { ...ANSWER, q: "zebra", hits: [], withheld: ["Customer"],
                withheld_said: ["only the Customer objects user:ana may see are shown"] });
  const user = userEvent.setup();
  render(<CommandPalette open onClose={vi.fn()} selectedConn="c1" onNavigate={vi.fn()} onGoToChat={vi.fn()} />);

  await user.type(screen.getByPlaceholderText(/search/i), "zebra");
  const none = await screen.findByTestId("objects-none");
  expect(none.textContent).toContain("No object is named");
  expect(none.textContent).toContain("searched 2 of 5 entities · some withheld from you");
  expect(none.getAttribute("title")).toContain("only the Customer objects user:ana may see");
});

it("with the flag off, nothing is fetched and no Objects group is shown", async () => {
  Element.prototype.scrollIntoView = vi.fn();
  const calls = serve(false);
  const user = userEvent.setup();
  render(<CommandPalette open onClose={vi.fn()} selectedConn="c1" onNavigate={vi.fn()} onGoToChat={vi.fn()} />);

  await user.type(screen.getByPlaceholderText(/search/i), "alice smith");
  await new Promise(r => setTimeout(r, 400));
  expect(calls.some(u => u.includes("/objects/find"))).toBe(false);
  expect(screen.queryByText("Objects")).toBeNull();
});
