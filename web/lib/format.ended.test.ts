import { describe, expect, it } from "vitest";

import { endedDay } from "./format";

describe("endedDay", () => {
  it("writes a day with its year, in UTC, for data that ended long ago", () => {
    expect(endedDay("2018-10-17")).toBe("Wed 17 Oct 2018");
    expect(endedDay("2018-10-17T23:30:00Z")).toBe("Wed 17 Oct 2018");
    expect(endedDay("not a day")).toBe("not a day");
  });
});
