// @vitest-environment jsdom
/**
 * The title over an answer's rows: a grain word ("Daily", "Monthly") only over rows that are a series in time — the date
 * column decided by the shared classifier, never by a name's ending alone.
 */
import { describe, expect, it } from "vitest";

import { inferSourceTitle } from "./ChatMessage";

describe("inferSourceTitle", () => {
  it("calls a count named like a date a count, not a day (a sheet's breakdown by status, 2026-10-27)", () => {
    const columns = ["order_status", "orders_without_carrier_date"];
    const rows = [["shipped", 1107], ["canceled", 550], ["invoiced", 314]];
    expect(inferSourceTitle(columns, rows)).toBe("Orders Without Carrier Date by Order Status");
  });

  it("still names the grain over a series of days", () => {
    const columns = ["order_date", "orders"];
    const rows = [["2018-08-01", 120], ["2018-08-02", 131], ["2018-08-03", 118]];
    expect(inferSourceTitle(columns, rows)).toBe("Daily Orders");
  });
});
