// @vitest-environment jsdom
/**
 * Connect opens the provider's consent in ONE new tab and leaves this one where it is.
 *
 * 2026-10-07: `window.open(url, "_blank", "noopener")` returns null by spec even when the tab
 * opens, so the blocked-pop-up fallback (`window.location.href = url`) always ran as well — the
 * person saw Google's page in a new window AND in the app's own tab.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getIntegrationsCatalog: vi.fn(),
  beginIntegrationConnect: vi.fn(),
  listMcpServers: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

import { IntegrationsPanel } from "@/components/IntegrationsPanel";

const GOOGLE = {
  id: "google", name: "Google", category: "Productivity", blurb: "The one Google app.",
  configured: true, client_id: "cid", secret_preview: "", redirect_uri: "", console_url: "",
  oauth_ready: true, alt_door: "", https_only: false, connection: null,
  products: [{ id: "gmail", name: "Gmail", blurb: "Search and read your email.",
               scopes: "https://www.googleapis.com/auth/gmail.readonly", connected: false,
               tools: ["Gmail · list messages"] }],
};

it("opens the consent in one new tab and leaves this one where it is", async () => {
  api.getIntegrationsCatalog.mockResolvedValue({ providers: [GOOGLE], redirect_uri: "http://localhost:8000/oauth/callback" });
  api.listMcpServers.mockResolvedValue({ servers: [] });
  api.beginIntegrationConnect.mockResolvedValue("https://accounts.google.com/o/oauth2/v2/auth?state=s1");
  const tab = { closed: false, opener: {} as unknown, location: { href: "" }, close: vi.fn() };
  const open = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
  const here = window.location.href;

  render(<IntegrationsPanel />);
  fireEvent.click(within(await screen.findByTestId("integration-product-gmail"))
    .getByRole("button", { name: /^connect$/i }));

  await waitFor(() => expect(tab.location.href).toBe("https://accounts.google.com/o/oauth2/v2/auth?state=s1"));
  expect(api.beginIntegrationConnect).toHaveBeenCalledWith("google", "gmail");
  // No `noopener` in the call: with it, open() returns null even on success.
  expect(open.mock.calls).toEqual([["about:blank", "_blank"]]);
  expect(tab.opener).toBeNull();
  expect(window.location.href).toBe(here);
  open.mockRestore();
});
