// @vitest-environment jsdom
/**
 * Integrations, redone to CLARITY (2026-10-13), on the live install's shape: Google's app set up with none of its five
 * products connected, Slack reached through its app with one bot listening, Microsoft not set up. The screen opens on
 * the figures, puts the half-set-up provider under Needs you with a Connect on the row, and keeps the technical facts —
 * the client id among them — behind Details.
 */
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getIntegrationsCatalog: vi.fn(),
  getSlackBots: vi.fn(),
  listUserAgents: vi.fn(),
  getConnections: vi.fn(),
  getManagedSupervisor: vi.fn(),
  getSupervisorKeyStatus: vi.fn(),
  listMcpServers: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

import { IntegrationsPanel } from "@/components/IntegrationsPanel";

const product = (id: string, name: string) => ({ id, name, blurb: `${name} things.`, scopes: `scope.${id}`, connected: false, tools: [] });
const GOOGLE = {
  id: "google", name: "Google", category: "Productivity", blurb: "The one Google app.", configured: true,
  client_id: "client-id-under-details", secret_preview: "abcd••••••", redirect_uri: "", console_url: "https://console.example",
  oauth_ready: true, alt_door: "", https_only: false, connection: null,
  products: [product("gmail", "Gmail"), product("sheets", "Google Sheets")],
};
const SLACK = {
  id: "slack", name: "Slack", category: "Communication", blurb: "Post and read as a Slack app.", configured: true,
  client_id: "x", secret_preview: "x••••••", redirect_uri: "", console_url: "", oauth_ready: false, alt_door: "slack_app",
  https_only: true, connection: null,
};
const MICROSOFT = {
  id: "microsoft", name: "Microsoft", category: "Productivity", blurb: "Outlook mail, OneDrive and Teams.", configured: false,
  client_id: "", secret_preview: "", redirect_uri: "", console_url: "", oauth_ready: true, alt_door: "", https_only: false,
  connection: null,
};
const BOT = {
  id: "sb_1", name: "Aughor", enabled: true, disabled_reason: "", liveness_hint: "", team_id: "T", bot_user_id: "U1",
  agent_id: "ua_1", connection_id: "c1", agent_view: false, channel_id: "", rehearse: false,
  listening: { supervisor_id: "s", since: "2026-10-12T22:49:18Z", last_seen_at: new Date().toISOString() },
};

it("opens on the figures, asks about the half-set-up provider, and keeps the client id behind Details", async () => {
  api.getIntegrationsCatalog.mockResolvedValue({ providers: [GOOGLE, SLACK, MICROSOFT], redirect_uri: "http://localhost:8000/oauth/callback" });
  api.getSlackBots.mockResolvedValue([BOT]);
  api.listUserAgents.mockResolvedValue([{ id: "ua_1", name: "The Look Analyst", connection_id: "c1" }]);
  api.getConnections.mockResolvedValue([{ id: "c1", name: "theLook" }]);
  api.getManagedSupervisor.mockResolvedValue({
    flag: true, managed: true, state: "running", pid: 1, started_at: "2026-10-12T22:49:16Z", restarts: 0, last_exit_code: null,
    last_error: "", command: [], cwd: "", preconditions: [], log_path: "",
    heartbeat: { supervisor_id: "s", since: "2026-10-12T22:49:18Z", last_seen_at: new Date().toISOString(), running: 1, failed: 0, fresh: true },
  });
  api.getSupervisorKeyStatus.mockResolvedValue({ issued: true, issued_at: "", previous_valid_until: "", grace_s: 600 });
  api.listMcpServers.mockResolvedValue({ servers: [] });

  render(<Theme><IntegrationsPanel /></Theme>);

  await screen.findByTestId("integration-figures");
  expect(screen.getByTestId("fig-connected-value").textContent).toBe("1 of 3");
  expect(screen.getByTestId("fig-connected").textContent).toContain("Slack, by its app");
  expect(screen.getByTestId("fig-bots-value").textContent).toBe("1");
  expect(await screen.findByTestId("fig-supervisor-value")).toHaveTextContent("Running");

  // Google's app is set up and nothing of it is connected: that needs a person, with the way to act on the row.
  const needs = screen.getByTestId("integration-needs");
  expect(needs.getAttribute("data-waiting")).toBe("true");
  const half = within(needs).getByTestId("needs-half-set-up");
  expect(half.textContent).toContain("Google is set up, but nothing is connected");
  expect(within(half).getByRole("button", { name: /connect/i })).toBeTruthy();
  // Slack is connected through its app and its bot listens — nothing about it needs anyone.
  expect(within(needs).queryByTestId("needs-bot")).toBeNull();

  // The bot's row names its agent and connection, never their ids.
  const bot = screen.getByTestId("slack-bot-row");
  expect(bot.textContent).toContain("answers as The Look Analyst · asks on theLook");

  // Read first: no form open, and the client id only behind Details.
  expect(screen.queryByTestId("integration-setup-google")).toBeNull();
  expect(screen.queryByText("client-id-under-details")).toBeNull();
  fireEvent.click(within(screen.getByTestId("integration-card-google")).getByRole("button", { name: /details/i }));
  const details = screen.getByTestId("integration-details-google");
  expect(details.textContent).toContain("client-id-under-details");
  // The secret is said to exist, never shown — not even its masked preview.
  expect(details.textContent).toContain("stored, encrypted — never shown");
  expect(details.textContent).not.toContain("abcd");
});

it("a stored client id the provider will refuse is said, and Connect is held until the app is fixed", async () => {
  // Found 2026-10-27: a placeholder left in the store was offered as configured, and Google answered invalid_client.
  const problem = "“demo-client-id.apps.googleusercontent.com” is not a Google client id — one looks like 1-a.apps.googleusercontent.com";
  api.getIntegrationsCatalog.mockResolvedValue({ providers: [{ ...GOOGLE, client_id_problem: problem, oauth_ready: false }],
    redirect_uri: "http://localhost:8000/oauth/callback" });
  api.getSlackBots.mockResolvedValue([]);
  api.listUserAgents.mockResolvedValue([]);
  api.getConnections.mockResolvedValue([]);
  api.getManagedSupervisor.mockResolvedValue({ flag: false, managed: false, state: "stopped", pid: null, started_at: "",
    restarts: 0, last_exit_code: null, last_error: "", command: [], cwd: "", preconditions: [], log_path: "", heartbeat: null });
  api.getSupervisorKeyStatus.mockResolvedValue({ issued: false, issued_at: "", previous_valid_until: "", grace_s: 600 });
  api.listMcpServers.mockResolvedValue({ servers: [] });
  render(<Theme><IntegrationsPanel /></Theme>);
  const row = await screen.findByTestId("needs-client-problem");
  expect(row.textContent).toContain("Google's stored client id is wrong");
  expect(within(row).getByRole("button", { name: "Edit app" })).toBeTruthy();
  expect(screen.queryByTestId("needs-half-set-up")).toBeNull();
  const card = screen.getByTestId("integration-card-google");
  expect(within(card).getByTestId("integration-client-problem-google").textContent).toContain("Connect is held until then");
  for (const b of within(card).getAllByRole("button", { name: "Connect" })) expect(b).toBeDisabled();
});

it("a card the provider did not grant on the last connect is named, so a sign-in alone never reads as connected", async () => {
  api.getIntegrationsCatalog.mockResolvedValue({ providers: [{ ...GOOGLE, withheld_products: ["Google Drive comments"] }],
    redirect_uri: "http://localhost:8000/oauth/callback" });
  api.getSlackBots.mockResolvedValue([]);
  api.listUserAgents.mockResolvedValue([]);
  api.getConnections.mockResolvedValue([]);
  api.getManagedSupervisor.mockResolvedValue({ flag: false, managed: false, state: "stopped", pid: null, started_at: "",
    restarts: 0, last_exit_code: null, last_error: "", command: [], cwd: "", preconditions: [], log_path: "", heartbeat: null });
  api.getSupervisorKeyStatus.mockResolvedValue({ issued: false, issued_at: "", previous_valid_until: "", grace_s: 600 });
  api.listMcpServers.mockResolvedValue({ servers: [] });
  render(<Theme><IntegrationsPanel /></Theme>);
  const line = await screen.findByTestId("integration-withheld-google");
  expect(line.textContent).toContain("Google did not grant Google Drive comments on the last connect");
});
