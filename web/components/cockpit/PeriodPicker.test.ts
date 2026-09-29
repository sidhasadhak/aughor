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
    expect(periodWords({ preset: "last_week" }, null)).toBe("Latest week");
    expect(periodWords({ preset: "standing" }, JULY)).toBe("As written");
  });
});
