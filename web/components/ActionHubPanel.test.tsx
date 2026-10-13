// @vitest-environment jsdom
/**
 * Notifications, redone to CLARITY (2026-10-13). The live install's screen was fifty identical failure rows from two
 * triggers that no longer exist, with nothing configured. It now opens on three figures, says nothing needs a person
 * (a removed trigger's failures are history), and folds the log to one row per trigger and outcome with its count.
 * A live trigger whose last send failed is the one thing that does need a person, with its Test on the row.
 */
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActionHubPanel } from "@/components/ActionHubPanel";

const REFUSED = "HTTPConnectionPool(host='127.0.0.1', port=9): Max retries exceeded with url: /hook "
  + "(Caused by NewConnectionError(\"HTTPConnection(host='127.0.0.1', port=9): Failed\"))";

const send = (i: number, over: Record<string, unknown>) => ({
  id: `l${i}`, trigger_id: "t1", trigger_name: "slack-ops", recommendation: "hi", status: "failed", http_status: null,
  error: "Trigger is disabled", fired_at: `2026-07-08T11:${String(i % 60).padStart(2, "0")}:00+00:00`, ...over,
});

/** The live log, 2026-10-13: 46 + 4 failures, both triggers since removed. */
const LIVE_LOGS = [
  ...Array.from({ length: 46 }, (_, i) => send(i, {})),
  ...Array.from({ length: 4 }, (_, i) => send(100 + i, {
    trigger_id: "744ec96b", trigger_name: "DS-7 blackhole", error: REFUSED, fired_at: `2026-08-31T21:0${i}:00+00:00`,
  })),
];

function serve(triggers: unknown[], logs: unknown[]) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
    ok: true,
    json: async () => (String(url).includes("/actions/triggers") ? { triggers } : { logs }),
  })));
}

const mount = () => render(<Theme><ActionHubPanel /></Theme>);

afterEach(() => vi.unstubAllGlobals());

describe("Notifications", () => {
  it("opens on the figures, needs nobody for a removed trigger's failures, and folds the log", async () => {
    serve([], LIVE_LOGS);
    mount();

    const figures = await screen.findByTestId("notification-figures");
    expect(within(screen.getByTestId("fig-triggers")).getByText("0")).toBeTruthy();
    expect(screen.getByTestId("fig-delivered-value").textContent).toBe("0");
    expect(screen.getByTestId("fig-failed-value").textContent).toBe("50");
    expect(figures.textContent).toContain("all from 2 triggers since removed");

    const needs = screen.getByTestId("notification-needs");
    expect(needs.getAttribute("data-waiting")).toBe("false");
    expect(needs.textContent).toBe("Needs youNothing needs you");

    // Fifty rows became two, each with its count; the removed trigger says so.
    const rows = screen.getAllByTestId("delivery-row");
    expect(rows).toHaveLength(2);
    expect(rows.map(r => within(r).getByTestId("delivery-count").textContent)).toEqual(["×4", "×46"]);
    expect(rows[1].textContent).toContain("slack-ops");
    expect(rows[1].textContent).toContain("the trigger was off");
    expect(rows[0].textContent).toContain("could not connect to 127.0.0.1:9");
    expect(screen.getAllByText("since removed")).toHaveLength(2);

    // Read first: the form is not open until a person asks for it.
    expect(screen.queryByTestId("trigger-form")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /new trigger/i }));
    expect(screen.getByTestId("trigger-form")).toBeTruthy();
  });

  it("puts a live trigger whose last send failed under Needs you, with its Test", async () => {
    serve(
      [{ id: "t1", name: "slack-ops", type: "slack", url: "https://hooks.slack.com/••••••", headers: {}, enabled: true, channel: "#ops" }],
      [send(1, { status: "ok", error: null, http_status: 200 }), send(2, { error: REFUSED }), send(3, { error: REFUSED })],
    );
    mount();

    const needs = await screen.findByTestId("notification-needs");
    await waitFor(() => expect(needs.getAttribute("data-waiting")).toBe("true"));
    const row = within(needs).getByTestId("needs-failing");
    expect(row.textContent).toContain("slack-ops · its last 2 sends failed");
    expect(within(row).getByRole("button", { name: "Test" })).toBeTruthy();
    expect(screen.getByTestId("fig-failed-value").textContent).toBe("2");

    // The trigger's row says where it sends — the channel and the host, never the hook's path.
    const trigger = screen.getByTestId("trigger-row");
    expect(trigger.textContent).toContain("#ops on hooks.slack.com");
    expect(trigger.textContent).not.toContain("••••••");
  });
});
