// @vitest-environment jsdom
/**
 * Connected sources (Documents) — the connect form is SERVED, never mirrored.
 *
 * The claims worth pinning:
 * * **The fields come from the payload.** A field added server-side (in the
 *   connector registry) must appear here with no frontend change — so the test
 *   feeds a field the real registry does not have and expects it rendered.
 * * **A secret field is a password input.** The flag travels with the field;
 *   the client decides nothing.
 * * **The server's refusal is shown verbatim** — the live credential test's
 *   words, not a re-worded summary.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { KnowledgeSourcesSection } from "@/components/KnowledgeSourcesSection";

const api = vi.hoisted(() => ({
  getKnowledgeSources: vi.fn(),
  createKnowledgeSource: vi.fn(),
  triggerKnowledgeSync: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

const payload = {
  types: [
    { conn_type: "notion", label: "Notion",
      fields: [
        { key: "integration_token", label: "Integration token", placeholder: "secret_…", secret: true },
        { key: "brand_new_field", label: "Brand new field", placeholder: "", secret: false },
      ] },
    { conn_type: "confluence", label: "Confluence", fields: [] },
  ],
  sources: [
    { id: "k1", name: "Team wiki", conn_type: "notion",
      status: { last_sync: "2026-09-06T10:00:00Z", pages_indexed: 42 } },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  api.getKnowledgeSources.mockResolvedValue(payload);
  api.createKnowledgeSource.mockResolvedValue({ id: "k2", message: "ok", test_result: "ok" });
  api.triggerKnowledgeSync.mockResolvedValue(undefined);
});

it("renders the connected source with its sync state", async () => {
  render(<KnowledgeSourcesSection />);
  expect(await screen.findByText("Team wiki")).toBeInTheDocument();
  expect(screen.getByText(/42 pages indexed/)).toBeInTheDocument();
});

it("builds the connect form from the SERVED fields, secrets as password inputs", async () => {
  render(<KnowledgeSourcesSection />);
  fireEvent.click(await screen.findByText("+ Notion"));

  const token = screen.getByPlaceholderText(/Integration token/);
  expect(token).toHaveAttribute("type", "password");
  // A field the real registry does not have yet — rendered purely from the payload.
  expect(screen.getByPlaceholderText(/Brand new field/)).toHaveAttribute("type", "text");
});

it("submits the typed config and refuses with the server's own words", async () => {
  api.createKnowledgeSource.mockRejectedValue(
    new Error("Source test failed: 401 from api.notion.com"));
  render(<KnowledgeSourcesSection />);
  fireEvent.click(await screen.findByText("+ Notion"));
  fireEvent.change(screen.getByPlaceholderText(/Name/), { target: { value: "My wiki" } });
  fireEvent.change(screen.getByPlaceholderText(/Integration token/), { target: { value: "secret_x" } });
  fireEvent.click(screen.getByText("Test & connect"));

  await waitFor(() => expect(api.createKnowledgeSource).toHaveBeenCalledWith(
    "notion", "My wiki", { integration_token: "secret_x" }));
  expect(await screen.findByText(/401 from api.notion.com/)).toBeInTheDocument();
});

it("Sync now triggers the existing per-connection sync route", async () => {
  render(<KnowledgeSourcesSection />);
  fireEvent.click(await screen.findByText("Sync now"));
  await waitFor(() => expect(api.triggerKnowledgeSync).toHaveBeenCalledWith("k1"));
});
