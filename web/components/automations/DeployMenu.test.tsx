// @vitest-environment jsdom
/**
 * DS-17 — the Deploy menu renders the SERVER's answer, and never its own.
 *
 * Two of these assertions look like style checks and are not. The alt-door rule lives
 * entirely in the `reason` sentence — a Slack door reading "connect via OAuth" is shaped
 * exactly like a correct one and points a self-hosted install at a door Slack refuses to
 * open for it — so a client that re-worded or hard-coded those sentences would be
 * re-deciding what this deployment can do. And a door whose state is `needs_setup` must
 * offer no verb here: its fix is on another screen, and a button that pretended otherwise
 * would fail in a way the reader cannot distinguish from the feature being broken.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeployMenu } from "@/components/automations/DeployMenu";
import type { AutomationDoor } from "@/lib/api";

const api = vi.hoisted(() => ({
  getAutomationDoors: vi.fn(),
  setAutomationEnabled: vi.fn(),
  setAutomationExposed: vi.fn(),
  issueAutomationWebhook: vi.fn(),
  revokeAutomationWebhook: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

const door = (over: Partial<AutomationDoor> = {}): AutomationDoor => ({
  kind: "schedule", label: "Schedule", description: "Runs itself on a cron cadence.",
  icon: "clock", priority: 10, state: "open", reason: "Running on 0 9 * * *.",
  detail: "0 9 * * *", ...over,
});

function show(doors: AutomationDoor[], summary = "Live on 1 door") {
  api.getAutomationDoors.mockResolvedValue({ doors, summary });
  render(<DeployMenu automationId="a1" />);
  fireEvent.click(screen.getByRole("button", { name: /deploy/i }));
}

beforeEach(() => {
  vi.clearAllMocks();
  api.setAutomationEnabled.mockResolvedValue({});
  api.setAutomationExposed.mockResolvedValue({});
  api.revokeAutomationWebhook.mockResolvedValue(undefined);
});

describe("the menu", () => {
  it("asks the server only when it is opened", async () => {
    api.getAutomationDoors.mockResolvedValue({ doors: [door()], summary: "Live on 1 door" });
    render(<DeployMenu automationId="a1" />);
    // Each read counts bots, reads the clock and looks for a tool-name clash; a canvas
    // that did that on every frame would pay for a menu nobody opened.
    expect(api.getAutomationDoors).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /deploy/i }));
    await waitFor(() => expect(api.getAutomationDoors).toHaveBeenCalledWith("a1"));
  });

  it("renders the server's sentence verbatim rather than one of its own", async () => {
    const reason = "No Slack bot on this deployment. Add one under Slack bots — the app "
      + "manifest path needs no public URL (Socket Mode connects outward).";
    show([door({ kind: "slack", label: "Slack", state: "needs_setup", reason, detail: "" })]);
    expect(await screen.findByText(reason)).toBeInTheDocument();
  });

  it("shows the one-line summary the server computed", async () => {
    show([door()], "Live on 2 doors");
    expect(await screen.findByText(/Live on 2 doors/)).toBeInTheDocument();
  });
});

describe("the verbs", () => {
  it("offers none for a door whose fix is on another screen", async () => {
    show([door({ kind: "slack", label: "Slack", state: "needs_setup",
                 reason: "No Slack bot on this deployment." })]);
    await screen.findByText(/No Slack bot/);
    expect(screen.queryByRole("button", { name: /turn on|offer|issue/i })).toBeNull();
  });

  it("turns a closed schedule on, and re-reads rather than guessing the new state", async () => {
    show([door({ state: "closed", reason: "The chain is switched off." })]);
    fireEvent.click(await screen.findByRole("button", { name: /turn on/i }));

    await waitFor(() => expect(api.setAutomationEnabled).toHaveBeenCalledWith("a1", true));
    // Twice: once on open, once after the verb. A menu that patched its own state locally
    // would report a door as open while the server had refused it.
    await waitFor(() => expect(api.getAutomationDoors).toHaveBeenCalledTimes(2));
  });

  it("offers the MCP tool without sending the whole record", async () => {
    show([door({ kind: "mcp_tool", label: "MCP tool", state: "closed",
                 reason: "Not offered.", detail: "daily_sales_report" })]);
    fireEvent.click(await screen.findByRole("button", { name: /offer as tool/i }));
    await waitFor(() => expect(api.setAutomationExposed).toHaveBeenCalledWith("a1", true));
  });
});

describe("the webhook credential", () => {
  const webhookDoor = (over: Partial<AutomationDoor> = {}) =>
    door({ kind: "webhook", label: "Webhook", icon: "link", state: "closed", detail: "",
           reason: "No URL has been issued.", ...over });

  it("shows the whole call, not a bare token, and says it is shown once", async () => {
    api.issueAutomationWebhook.mockResolvedValue({
      automation_id: "a1", token: "tok_secret", url: "http://localhost:8000/hooks/a1",
      header: "Authorization: Bearer <token>",
    });
    show([webhookDoor()]);
    fireEvent.click(await screen.findByRole("button", { name: /issue url/i }));

    const call = await screen.findByText(/curl -X POST/);
    expect(call).toHaveTextContent("http://localhost:8000/hooks/a1");
    expect(call).toHaveTextContent("Authorization: Bearer tok_secret");
    expect(screen.getByText(/shown once/i)).toBeInTheDocument();
  });

  it("forgets the plaintext when the dialog closes", async () => {
    api.issueAutomationWebhook.mockResolvedValue({
      automation_id: "a1", token: "tok_secret", url: "http://localhost:8000/hooks/a1",
      header: "Authorization: Bearer <token>",
    });
    show([webhookDoor()]);
    fireEvent.click(await screen.findByRole("button", { name: /issue url/i }));
    await screen.findByText(/curl -X POST/);

    // Escape closes the dialog. Keeping the token across opens would turn a shown-once
    // credential into one that lives in the tab until a reload.
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText(/curl -X POST/)).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: /deploy/i }));
    await screen.findByText(/No URL has been issued/);
    expect(screen.queryByText(/curl -X POST/)).toBeNull();
  });

  it("offers Revoke only once a URL exists", async () => {
    show([webhookDoor()]);
    await screen.findByText(/No URL has been issued/);
    expect(screen.queryByRole("button", { name: /revoke/i })).toBeNull();
  });

  it("offers Rotate on an open door, because rotating is the remedy for a leak", async () => {
    show([webhookDoor({ state: "open", detail: "issued 2026-09-02T10:00:00Z",
                        reason: "Anything holding the token can run this chain." })]);
    expect(await screen.findByRole("button", { name: /rotate/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /revoke/i })).toBeInTheDocument();
  });
});
