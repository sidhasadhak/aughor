import { describe, expect, it } from "vitest";

import { draftedFigure } from "./figureText";

describe("a figure drafted from a file", () => {
  it("is written as its statement says it is", () => {
    expect(draftedFigure(1072874.42, "money")).toBe("$1,072,874");
    expect(draftedFigure(0.262, "percent")).toBe("26.2%");
    expect(draftedFigure(20957, "number")).toBe("20,957");
    expect(draftedFigure(20957)).toBe("20,957");
  });
  it("says it has nothing, rather than a zero", () => {
    expect(draftedFigure(null, "money")).toBe("—");
    expect(draftedFigure(null, "percent")).toBe("—");
  });
});
