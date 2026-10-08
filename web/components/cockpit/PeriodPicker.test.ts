import { describe, expect, it } from "vitest";

import { periodWords } from "@/components/cockpit/PeriodPicker";
import type { CockpitRange } from "@/lib/api";

const JULY: CockpitRange = {
  status: "final", preset: "last_month", start: "2026-07-01", last_day: "2026-07-31", covers: "July 2026",
  as_of: "2026-09-28", lag_days: 29, still_moving: [],
};

describe("what the period menu says", () => {
  it("is the period itself, as the server resolved it, and whether it has settled", () => {
    expect(periodWords({ preset: "last_month" }, JULY)).toBe("July 2026 · final");
    expect(periodWords({ preset: "month_to_date" }, { ...JULY, status: "to_date", covers: "September 2026 to date" }))
      .toBe("September 2026 to date · to date");
  });

  it("is the choice's name until a range is read, and 'As written' with none", () => {
    expect(periodWords({ preset: "previous_week" }, null)).toBe("Last week");
    expect(periodWords({ preset: "current_day" }, null)).toBe("Current day");
    expect(periodWords({ preset: "standing" }, JULY)).toBe("As written");
  });

  it("while a new period is read, names it — never the period still on screen", () => {
    expect(periodWords({ preset: "current_week" }, JULY, true)).toBe("Current week · reading…");
    expect(periodWords({ preset: "custom", start: "2026-10-01", end: "2026-10-07" }, JULY, true))
      .toBe("2026-10-01 to 2026-10-07 · reading…");
  });
});
