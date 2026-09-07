// @vitest-environment jsdom
/**
 * Creating a connection must not close the panel on hope (2026-09-07).
 *
 * The old submit did `await addConnection(); onAdded(); onClose();` — it fired the
 * catalogue refresh WITHOUT awaiting it and closed immediately. The user landed on
 * a Catalog that did not list what they had just created, and a connection that
 * never became visible (the workspace-membership bug) looked exactly like a slow
 * one. "I removed it and added it again and sometimes it just does not show up."
 *
 * Pinned here:
 *   * the active workspace travels with the create — it is what makes the new
 *     connection visible in THIS workspace's tree;
 *   * the panel stays open until `onAdded` resolves, and closes once it confirms;
 *   * when the connection never appears, the panel stays open and SAYS so rather
 *     than closing silently.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { AddDataPanel } from "@/components/AddDataPanel";

const api = vi.hoisted(() => ({
  addConnection: vi.fn(),
  getConnectorTypes: vi.fn(),
  listConnectionSchemas: vi.fn(),
  listConnectionFiles: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

// Shape matters: the picker groups by `category`, so a fixture without one renders
// no tiles at all (which is how the first draft of this test failed).
const TYPES = [{
  type: "postgres",
  dsn_preview: "postgres://…",
  category: "built-in",
  available: true,
  fields: [{ key: "dsn", label: "DSN", placeholder: "postgres://…", secret: false }],
}];

beforeEach(() => {
  vi.clearAllMocks();
  api.getConnectorTypes.mockResolvedValue(TYPES);
  api.listConnectionSchemas.mockResolvedValue(["main"]);
  api.listConnectionFiles.mockResolvedValue([]);
  api.addConnection.mockResolvedValue({ id: "abc123", message: "ok", test_result: "" });
});

/** Pick the Postgres tile and fill the DSN, leaving the form ready to submit. */
async function openForm() {
  // The tile's visible label comes from the panel's own META table ("PostgreSQL"),
  // not from the payload's type — query by role so the label can change freely.
  const tile = await screen.findByRole("button", { name: /PostgreSQL/i });
  fireEvent.click(tile);
  const dsn = await screen.findByPlaceholderText("postgres://…");
  fireEvent.change(dsn, { target: { value: "postgres://localhost/db" } });
  return dsn;
}

function submitForm() {
  const btn = screen.getByRole("button", { name: /create connection/i });
  fireEvent.click(btn);
}

it("sends the active workspace, so the new connection lands where the user is looking", async () => {
  const onAdded = vi.fn().mockResolvedValue(true);
  render(<AddDataPanel onClose={vi.fn()} onAdded={onAdded} workspaceId="ws-analytics" />);
  await openForm();
  submitForm();

  await waitFor(() => expect(api.addConnection).toHaveBeenCalled());
  // last positional argument is the workspace
  const args = api.addConnection.mock.calls[0];
  expect(args[args.length - 1]).toBe("ws-analytics");
});

it("stays open until the catalogue confirms, then closes", async () => {
  let release: (v: boolean) => void = () => {};
  const onAdded = vi.fn().mockReturnValue(new Promise<boolean>(r => { release = r; }));
  const onClose = vi.fn();
  render(<AddDataPanel onClose={onClose} onAdded={onAdded} workspaceId="ws" />);
  await openForm();
  submitForm();

  await waitFor(() => expect(onAdded).toHaveBeenCalledWith("abc123"));
  expect(onClose).not.toHaveBeenCalled();   // the refresh is still in flight

  release(true);
  await waitFor(() => expect(onClose).toHaveBeenCalled());
});

it("does not close silently when the connection never appears", async () => {
  const onAdded = vi.fn().mockResolvedValue(false);
  const onClose = vi.fn();
  render(<AddDataPanel onClose={onClose} onAdded={onAdded} workspaceId="ws" />);
  await openForm();
  submitForm();

  await waitFor(
    () => expect(screen.getByText(/has not appeared in the catalogue/i)).toBeTruthy(),
    { timeout: 5000 },
  );
  expect(onClose).not.toHaveBeenCalled();
}, 10000);
