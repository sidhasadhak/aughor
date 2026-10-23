// @vitest-environment jsdom
/**
 * Monitors, redone to CLARITY.md: four figures (how many, open alerts, proven to fire, checks a day), then what needs
 * a person with its buttons on the row, then the monitors one line each with their detail behind Details — and the
 * Alerts view saying an alert that repeats once, with its count.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MonitorAlert, MonitorDef, MonitorProof } from "@/lib/api";

const monitor = (over: Partial<MonitorDef>): MonitorDef => ({
  id: "m1", conn_id: "c1", name: "Average Order Value", metric_name: null,
  custom_sql: "SELECT SAFE_DIVIDE(SUM(sale_price), COUNT(DISTINCT order_id)) FROM order_items", reanchor_window: false,
  check_cron: "0 * * * *", alert_on: "threshold_cross", warning_threshold: 86, critical_threshold: null, threshold_direction: "below",
  sigma_threshold: 2.5, history_days: 30, dimension_column: null, freshness_table: null, freshness_column: null,
  freshness_sla_hours: 24, drift_p_threshold: null, grace_period_hours: 4, notification_channel: "in_app", enabled: true,
  created_at: "2026-09-30T20:34:13Z", updated_at: "2026-09-30T20:34:13Z", ...over,
});
const MONITORS = [
  monitor({}),
  monitor({ id: "m2", name: "Units Sold anomaly watch", alert_on: "anomaly", check_cron: "0 9 * * *", sigma_threshold: 3 }),
];
const alert = (over: Partial<MonitorAlert>): MonitorAlert => ({
  id: "a1", monitor_id: "m1", monitor_name: "Average Order Value", conn_id: "c1", metric_name: null,
  triggered_at: new Date(Date.now() - 2 * 86_400_000).toISOString(), alert_on: "threshold_cross", severity: "warning",
  current_value: 81.2, previous_value: 88.4, threshold: 86, message: "Average Order Value: 81.2 below warning threshold 86",
  caveat: null, acknowledged: false, acknowledged_at: null, ...over,
});
const ALERTS = [alert({ id: "a1" }), alert({ id: "a2" }), alert({ id: "a3" })];
const PROOFS: Record<string, MonitorProof> = {
  m1: { monitor_id: "m1", sentence: "never proven — no drill, no delivered alert", last_drill: null },
  m2: { monitor_id: "m2", sentence: "the rule fired in a drill on 2026-09-23T12:16:05+00:00; delivery not attempted",
    last_drill: { monitor_id: "m2", at: "2026-09-23T12:16:05+00:00", fired: true, delivered: null, detail: "", channel: "in_app" } },
};

const api = vi.hoisted(() => ({
  getMonitors: vi.fn(),
  getAllAlerts: vi.fn(),
  getMetrics: vi.fn(async () => []),
  getMonitorProof: vi.fn(),
  acknowledgeAlert: vi.fn(async (id: string) => ({ id, acknowledged: true })),
  drillMonitor: vi.fn(async (id: string) => ({ monitor_id: id, at: "", fired: true, delivered: null, detail: "", channel: "in_app" })),
}));
vi.mock("@/lib/api", async importOriginal => ({ ...(await importOriginal<typeof import("@/lib/api")>()), ...api }));

import { MonitorsPanel } from "./MonitorsPanel";

afterEach(() => { vi.clearAllMocks(); });

function serve(alerts: MonitorAlert[] = ALERTS) {
  api.getMonitors.mockResolvedValue(MONITORS);
  api.getAllAlerts.mockResolvedValue(alerts);
  api.getMonitorProof.mockImplementation(async (id: string) => PROOFS[id]);
}
const panel = () => render(<Theme><MonitorsPanel connId="c1" workspaceId="w1" /></Theme>);

describe("MonitorsPanel", () => {
  it("leads with four figures read from the monitors, their alerts and their proofs", async () => {
    serve();
    panel();
    await waitFor(() => expect(screen.getByTestId("fig-proven")).toHaveTextContent("1 of 2"));
    expect(screen.getByTestId("monitor-figures").children).toHaveLength(4);
    expect(screen.getByTestId("fig-monitors")).toHaveTextContent("2all on");
    expect(screen.getByTestId("fig-open")).toHaveTextContent("3");
    expect(screen.getByTestId("fig-proven")).toHaveTextContent("none delivered end to end");
    // one hourly (24) and one daily (1)
    expect(screen.getByTestId("fig-checks")).toHaveTextContent("25");
    expect(screen.getByTestId("fig-checks")).toHaveTextContent("1 hourly · 1 daily");
    // the scope the shell gave is the scope read
    expect(api.getMonitors).toHaveBeenCalledWith("c1", "w1");
  });

  it("puts open alerts and a monitor never proven under Needs you, with their buttons on the row", async () => {
    serve();
    panel();
    const open = await screen.findByTestId("needs-open");
    expect(open).toHaveTextContent("Average Order Value · 3 open alerts");
    fireEvent.click(within(open).getByRole("button", { name: "Acknowledge all" }));
    await waitFor(() => expect(api.acknowledgeAlert).toHaveBeenCalledTimes(3));

    const never = await screen.findByTestId("needs-never");
    expect(never).toHaveTextContent("1 monitor has never been proven to fire");
    fireEvent.click(within(never).getByRole("button", { name: "Check its rule" }));
    // a check proves the rule and sends nothing
    await waitFor(() => expect(api.drillMonitor).toHaveBeenCalledWith("m1", false));
  });

  it("draws each monitor as one line — rule, schedule, channel and proof as marks — its detail behind Details", async () => {
    serve();
    panel();
    await waitFor(() => expect(screen.getAllByTestId("monitor-row")).toHaveLength(2));
    const [aov, units] = screen.getAllByTestId("monitor-row");
    expect(aov).toHaveTextContent("Threshold · below 86 · hourly · in-app · your own query");
    expect(within(aov).getByText("never proven")).toHaveAttribute("title", "never proven — no drill, no delivered alert");
    expect(within(aov).getByText("3 open")).toBeInTheDocument();
    expect(within(units).getByText("rule checked 23 Sep · not delivered")).toBeInTheDocument();
    // Edit, Delete and the three proofs live behind Details
    expect(within(aov).queryByRole("button", { name: "Delete" })).toBeNull();
    fireEvent.click(within(aov).getByRole("button", { name: /Details/ }));
    const details = within(aov).getByTestId("monitor-details");
    for (const name of ["Backtest", "Check rule", "Send test alert", "Edit", "Delete"]) {
      expect(within(details).getByRole("button", { name })).toBeInTheDocument();
    }
    expect(details).toHaveTextContent("SAFE_DIVIDE(SUM(sale_price)");
  });

  it("says an alert that repeats once, with its count, on the Alerts view", async () => {
    serve([...ALERTS, alert({ id: "old", acknowledged: true, monitor_id: "gone", monitor_name: "Active Customer Count",
      message: "Active Customer Count: 2.026e+04 above warning threshold 2e+04", triggered_at: "2026-08-24T06:00:00Z" })]);
    panel();
    fireEvent.click(within(await screen.findByTestId("needs-open")).getByRole("button", { name: "See alerts" }));
    const rows = await screen.findAllByTestId("alert-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("×3");
    expect(within(rows[0]).getByRole("button", { name: "Acknowledge 3" })).toBeInTheDocument();
    // humanised, and settled — and its monitor, gone, is said to be
    expect(rows[1]).toHaveTextContent("20,260 above warning threshold 20,000");
    expect(rows[1]).toHaveTextContent("acknowledged");
    expect(rows[1]).toHaveTextContent("since removed");
    expect(rows[0]).not.toHaveTextContent("since removed");
  });

  it("says nothing needs the reader, in one line, when nothing does", async () => {
    serve([]);
    api.getMonitorProof.mockImplementation(async (id: string) => PROOFS.m2 && { ...PROOFS.m2, monitor_id: id });
    panel();
    await waitFor(() => expect(screen.getByTestId("monitor-needs"))
      .toHaveTextContent("Nothing needs you · no open alert, and every monitor has been seen to fire"));
    expect(screen.getByTestId("fig-open")).toHaveTextContent("none has fired here yet");
    // nothing to picture: the figure already says it
    expect(screen.queryByTestId("monitor-alert-weeks")).toBeNull();
  });

  it("says alerts of monitors since removed apart, never as the workspace's own (the Olist workspace, 2026-10-23)", async () => {
    const gone = (id: string, monitor_id: string, monitor_name: string, at: string) =>
      alert({ id, monitor_id, monitor_name, acknowledged: true, triggered_at: at, message: `${monitor_name}: 1 below warning threshold 2` });
    api.getMonitors.mockResolvedValue([monitor({ id: "gmv", name: "Monthly GMV floor" })]);
    api.getAllAlerts.mockResolvedValue([
      gone("o1", "acc", "Active Customer Count", new Date(Date.now() - 9 * 86_400_000).toISOString()),
      gone("o2", "acc", "Active Customer Count", new Date(Date.now() - 10 * 86_400_000).toISOString()),
      gone("o3", "demo", "WP-1b caveat demo", new Date(Date.now() - 200 * 86_400_000).toISOString()),
    ]);
    api.getMonitorProof.mockResolvedValue(PROOFS.m1);
    panel();
    await waitFor(() => expect(screen.getByTestId("fig-open")).toHaveTextContent("all from 2 monitors since removed"));
    expect(screen.getByTestId("fig-open")).toHaveTextContent("3 acknowledged");
    // the twelve weeks hold two of them, both from the one removed monitor
    expect(screen.getByTestId("monitor-alert-weeks")).toHaveTextContent("2 alerts · all from 1 monitor since removed");
  });
});
