// @vitest-environment jsdom
/**
 * Security & Audit, redone to CLARITY.md: a row of figures, then Needs you, then who ran the queries, then the checks
 * folded — 477 near-identical rows become two, and the platform's own flagged reads are named as noise. Nothing true
 * is lost: the probes the log does not list still say so, and every row is one Show away with its SQL.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getConnections: vi.fn(async () => [{ id: "c1", name: "theLook", conn_type: "bigquery" }]),
  getApprovalsAudit: vi.fn(async () => [
    { seq: 3, at: "2026-10-11T12:26:39Z", action: "connection.delete", risk: "high", decision: "approved", scope: "a1", actor: "amit" },
    { seq: 2, at: "2026-10-11T12:20:00Z", action: "connection.delete", risk: "high", decision: "approved", scope: "a2", actor: "amit" },
    { seq: 1, at: "2026-10-10T10:00:00Z", action: "metric.approve", risk: "high", decision: "blocked", scope: "aov", actor: "amit" },
  ]),
  getAllowlist: vi.fn(async () => [
    { action: "connection.delete", scope: "a1", by: "amit", at: "2026-10-11T22:00:04Z" },
    { action: "connection.delete", scope: "a2", by: "amit", at: "2026-10-11T22:00:08Z" },
    { action: "connection.delete", scope: "a3", by: "amit", at: "2026-10-11T22:00:09Z" },
  ]),
  revokeApproval: vi.fn(async () => undefined),
}));

import { SecurityAuditPanel } from "./SecurityAuditPanel";

const STATS = {
  total: 147826, blocked: 843, suspicious: 22770, errors: 11349, pii_redacted: 17614, avg_duration_ms: 482.77,
  internal_statements: 19920, internal_since: "2026-09-30",
};

let n = 0;
const rec = (over: Record<string, unknown>) => ({
  id: `r${++n}`, ts: "2026-10-11T23:40:00Z", connection_id: "c1", hypothesis_id: "__brief_period__",
  sql_digest: "SELECT 'current' AS _w", sql_full: "SELECT 'current' AS _w, (SELECT SUM(sale_price) FROM order_items)",
  verdict: "safe", row_count: 3, duration_ms: 612, pii_redacted: 0, error: null, ...over,
});

/** The measured shape: 365 passed reads and 112 flags on the platform's own column-type reads. */
const NOISE = [
  ...Array.from({ length: 365 }, () => rec({})),
  ...Array.from({ length: 112 }, () => rec({ hypothesis_id: "__trust_coltypes__", verdict: "suspicious", row_count: 0, duration_ms: 0 })),
];

function serve(records: unknown[], blocked: unknown[] = []) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    const body = url.pathname === "/security/audit/stats" ? STATS
      : url.pathname === "/security/audit" ? { records: url.searchParams.get("verdict") === "blocked" ? blocked : records }
      : url.pathname.startsWith("/security/budget/") ? { connection_id: "c1", max_rows: 10000, warn_time_ms: 15000, max_time_ms: 60000, is_default: true }
      : {};
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
}

const realFetch = globalThis.fetch;
beforeEach(() => { n = 0; });
afterEach(() => { globalThis.fetch = realFetch; vi.clearAllMocks(); });

const panel = (lens: "security" | "approvals" = "security") =>
  render(<Theme><SecurityAuditPanel connId="c1" lens={lens} /></Theme>);

describe("SecurityAuditPanel · queries", () => {
  it("leads with four figures, the flags named as the platform's own", async () => {
    serve(NOISE, [rec({ verdict: "blocked", error: "DROP statements are not permitted", ts: "2026-09-12T07:19:35Z" })]);
    panel();
    const figures = await screen.findByTestId("audit-figures");
    expect(within(screen.getByTestId("fig-checked")).getByText("147.8K")).toBeInTheDocument();
    expect(screen.getByTestId("fig-checked")).toHaveTextContent("11.3K errors · avg 483 ms");
    expect(screen.getByTestId("fig-blocked")).toHaveTextContent("843");
    expect(screen.getByTestId("fig-blocked")).toHaveTextContent("refused before running · last 12 Sep");
    expect(screen.getByTestId("fig-flagged")).toHaveTextContent("22.8K");
    expect(screen.getByTestId("fig-flagged")).toHaveTextContent("112 recent, all the platform's own");
    expect(screen.getByTestId("fig-masked")).toHaveTextContent("17.6K");
    expect(figures.children).toHaveLength(4);
    // a refusal a month old needs nobody; nor does the platform talking to itself
    expect(screen.getByTestId("audit-needs")).toHaveTextContent("Nothing needs you");
  });

  it("folds 477 checks into two rows with their counts, each row's statements one Show away", async () => {
    serve(NOISE);
    panel();
    await waitFor(() => expect(screen.getAllByTestId("check-group")).toHaveLength(2));
    const [flags, passed] = screen.getAllByTestId("check-group");
    expect(flags).toHaveTextContent("Flagged · Trust check · column types");
    expect(flags).toHaveTextContent("the platform's own reads — flagged before they ran, then run");
    expect(within(flags).getByTestId("check-group-count")).toHaveTextContent("112");
    expect(passed).toHaveTextContent("Passed · Briefer · period comparison");
    expect(within(passed).getByTestId("check-group-count")).toHaveTextContent("365");
    // no row of the log is drawn until a person asks for it
    expect(screen.queryAllByRole("row")).toHaveLength(0);
    fireEvent.click(within(flags).getByRole("button", { name: /Show/ }));
    expect(within(flags).getAllByRole("row")).toHaveLength(1 + 112);
    fireEvent.click(within(flags).getAllByRole("button", { name: /SELECT 'current'/ })[0]);
    expect(within(flags).getByText(/SUM\(sale_price\) FROM order_items/)).toBeInTheDocument();
  });

  it("still says what the log does not list: the platform's probes, counted", async () => {
    serve(NOISE);
    panel();
    const chip = await screen.findByTestId("audit-not-listed");
    expect(chip).toHaveTextContent("19.9K probes not listed · since 30 Sep");
    expect(chip.getAttribute("title")).toMatch(/^Not listed here: 19,920 queries the platform ran for its own checks/);
    expect(screen.getByTestId("audit-checks")).toHaveTextContent("latest 477 checks of 147.8K");
  });

  it("puts a person's flagged query and a refusal this week under Needs you, with Review on the row", async () => {
    const mine = rec({ hypothesis_id: "query_workbench", verdict: "suspicious", sql_digest: "SELECT * FROM users UNION SELECT" });
    const refused = rec({ hypothesis_id: "query_builder", verdict: "blocked", error: "DROP statements are not permitted",
      ts: new Date(Date.now() - 86_400_000).toISOString() });
    serve([mine, ...NOISE], [refused]);
    panel();
    const asked = await screen.findByTestId("needs-asked");
    expect(asked).toHaveTextContent("1 flagged query from people or agents");
    expect(asked).toHaveTextContent("You · SQL Editor 1");
    expect(screen.getByTestId("needs-blocked")).toHaveTextContent("1 query blocked this week");
    expect(screen.getByTestId("fig-flagged")).toHaveTextContent("1 recent from people or agents");
    fireEvent.click(within(asked).getByRole("button", { name: "Review" }));
    const mineGroup = screen.getAllByTestId("check-group").find(g => g.textContent?.includes("You · SQL Editor"))!;
    expect(within(mineGroup).getAllByRole("row")).toHaveLength(2);
  });

  it("says a failed read and offers to read again", async () => {
    globalThis.fetch = vi.fn(async () => new Response("no", { status: 500 })) as typeof fetch;
    panel();
    expect(await screen.findByText(/Could not read the audit log/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

describe("SecurityAuditPanel · approvals", () => {
  it("folds the pre-approved actions and the decisions by action, each Revoke one Show away", async () => {
    serve([]);
    panel("approvals");
    const allowed = await screen.findByRole("region", { name: "Pre-approved actions" });
    await waitFor(() => expect(allowed).toHaveTextContent("connection delete"));
    expect(allowed).toHaveTextContent("a1 · a2 · +1 more");
    expect(screen.queryAllByRole("button", { name: "Revoke" })).toHaveLength(0);
    fireEvent.click(within(allowed).getByRole("button", { name: /Show/ }));
    expect(screen.getAllByRole("button", { name: "Revoke" })).toHaveLength(3);
    // one row per action, its decisions said as counts, refusals first
    const rows = screen.getAllByTestId("decision-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("connection delete");
    expect(rows[0]).toHaveTextContent("2 approved · last 11 Oct, amit");
    expect(rows[1]).toHaveTextContent("1 blocked");
    // the raw trail stays one click away
    fireEvent.click(screen.getByRole("button", { name: /Full trail/ }));
    expect(screen.getAllByText("connection.delete")).toHaveLength(2);
  });
});
