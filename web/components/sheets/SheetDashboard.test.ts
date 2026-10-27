import { describe, expect, it } from "vitest";

import { pieceWords } from "./SheetDashboard";
import { cardsDashboardSpec } from "@/lib/dashboards/start";
import type { DashboardPiece } from "@/lib/sheets";

const piece = (over: Partial<DashboardPiece>): DashboardPiece => ({
  key: "k", title: "t", kind: "figure", size: "small", why: "", shown: {}, ...over,
});

describe("a piece offered for a sheet's dashboard, in words", () => {
  it("says a figure, money in its currency, and empty as empty", () => {
    expect(pieceWords(piece({ preview: { value: 99441 } }))).toBe("99,441");
    expect(pieceWords(piece({ currency: "BRL", preview: { value: "16008872.12" } }))).toBe("R$16,008,872.12");
    expect(pieceWords(piece({ preview: { value: null } }))).toBe("empty");
  });

  it("names a bar's largest values and how many more there are", () => {
    expect(pieceWords(piece({ kind: "bar", preview: { values: [{ x: "delivered", v: 96478 }, { x: null, v: 2 }], of: 8 } })))
      .toBe("delivered 96,478 · empty 2 · 6 more");
  });

  it("says the months a line runs over, and the rows a table lists", () => {
    expect(pieceWords(piece({ kind: "line", preview: { points: 25, first: "2016-09-01", last: "2018-09-01" } })))
      .toBe("25 months, September 2016 to September 2018");
    expect(pieceWords(piece({ kind: "table", preview: { rows: 200, more: true } }))).toBe("200+ rows listed");
  });
});

describe("the dashboard a sheet's cards are kept in", () => {
  it("is one section of the kept cards, in the order they were offered, each at its size", () => {
    const spec = cardsDashboardSpec("Olist orders", [{ card: "k1", size: "small" }, { card: "k2", size: "wide" }]);
    const section = Object.values(spec.elements).find(e => e.type === "Section")!;
    expect(spec.elements[spec.root].children).toHaveLength(1);
    expect(section.children.map(k => spec.elements[k].props)).toEqual([{ card: "k1", size: "small" }, { card: "k2", size: "wide" }]);
    expect(spec.elements[spec.root].props.title).toBe("Olist orders");
  });
});
