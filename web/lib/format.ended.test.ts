import { describe, expect, it } from "vitest";

import { endedDay, spanWords } from "./format";

describe("endedDay", () => {
  it("writes a day with its year, in UTC, for data that ended long ago", () => {
    expect(endedDay("2018-10-17")).toBe("Wed 17 Oct 2018");
    expect(endedDay("2018-10-17T23:30:00Z")).toBe("Wed 17 Oct 2018");
    expect(endedDay("not a day")).toBe("not a day");
  });
});

describe("spanWords", () => {
  it("says a span as short as a table cell can", () => {
    expect(spanWords("2018-10-17", "2018-10-17")).toBe("Wed 17 Oct 2018");
    expect(spanWords("2018-09-01", "2018-09-30")).toBe("September 2018");
    expect(spanWords("2017-01-01", "2017-12-31")).toBe("2017");
    expect(spanWords("2018-10-01", "2018-10-17")).toBe("1–17 Oct 2018");
    expect(spanWords("2018-10-08", "2018-10-14")).toBe("8–14 Oct 2018");
    expect(spanWords("2018-01-01", "2018-10-17")).toBe("1 Jan – 17 Oct 2018");
    expect(spanWords("2017-10-01", "2018-03-31")).toBe("1 Oct 2017 – 31 Mar 2018");
    expect(spanWords(undefined, "2018-10-17")).toBe("");
  });
});
