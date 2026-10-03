/**
 * DE-5's hygiene (ROADMAP §3.51, the dbx study's finding 9) — a CSV export never hands a
 * spreadsheet a formula to run.
 *
 * `toCsv` is the one CSV door (five surfaces import it), so this is the one place the
 * judgement is tested. The receipt is the byte string: what a spreadsheet opens.
 */
import { describe, expect, it } from "vitest";
import { formulaCellCount, isFormulaLead, neutraliseFormula, toCsv, toTsv } from "./csv";

describe("isFormulaLead — what a spreadsheet would run", () => {
  it("is true for the four formula openers and the two characters that carry one", () => {
    for (const s of ['=HYPERLINK("http://x","y")', "@SUM(A1)", "+cmd|' /C calc'!A0", "-A1", "\t=1+1", "\r=1+1"]) {
      expect(isFormulaLead(s), s).toBe(true);
    }
  });

  it("is false for a plain number, signed or not — a negative amount must open as a number", () => {
    for (const s of ["-5", "+3", "-1.5", "-.5", "-1.5e3", "+2E-7", "5", "0", "-", "+"]) {
      expect(isFormulaLead(s), s).toBe(false);
    }
  });

  it("is false for a signed number as people write one: currency, digit groups, a percent", () => {
    // An answer table's change column, as the model writes it (TableActions.test.tsx's fixture).
    for (const s of ["-$5,421.84", "+$7,463.84", "-5%", "+12 %", "-€1.234,56", "-1 000,5", "+₹1,099"]) {
      expect(isFormulaLead(s), s).toBe(false);
    }
  });

  it("is true for a signed expression or signed text, which a spreadsheet evaluates", () => {
    expect(isFormulaLead("-1+1")).toBe(true);
    expect(isFormulaLead("+1*A2")).toBe(true);
    expect(isFormulaLead("-5 days")).toBe(true);
  });

  it("is false for ordinary text, an empty string and a leading space", () => {
    for (const s of ["hello", "", " =1+1", "a=b", "x@y.com", "2024-01-01"]) {
      expect(isFormulaLead(s), s).toBe(false);
    }
  });
});

describe("neutraliseFormula", () => {
  it("prefixes a string that opens like a formula with a visible apostrophe", () => {
    expect(neutraliseFormula("=1+1")).toBe("'=1+1");
    expect(neutraliseFormula("-A1")).toBe("'-A1");
  });

  it("never touches a number, a boolean, a null or a plain string", () => {
    expect(neutraliseFormula(-5)).toBe("-5");
    expect(neutraliseFormula(true)).toBe("true");
    expect(neutraliseFormula(null)).toBe("");
    expect(neutraliseFormula(undefined)).toBe("");
    expect(neutraliseFormula("-5")).toBe("-5");
    expect(neutraliseFormula("hello")).toBe("hello");
  });
});

describe("toCsv", () => {
  it("writes a formula cell as text, quoted as RFC 4180 requires", () => {
    const out = toCsv(["name", "link"], [["a", '=HYPERLINK("http://x","y")']]);
    expect(out).toBe('name,link\r\na,"\'=HYPERLINK(""http://x"",""y"")"');
  });

  it("keeps every number a number, including negatives from the typed and the legacy path", () => {
    expect(toCsv(["n", "s"], [[-5, "-5"], [1.5, "-1.5e3"]])).toBe("n,s\r\n-5,-5\r\n1.5,-1.5e3");
  });

  it("neutralises a column NAME that opens like a formula too — it is a cell in the sheet", () => {
    expect(toCsv(["=x", "y"], [[1, 2]])).toBe("'=x,y\r\n1,2");
  });

  it("still quotes a comma, a quote, CR and LF, doubles embedded quotes, and empties a NULL", () => {
    const out = toCsv(["a", "b", "c"], [['say "hi"', "x,y", null], ["line\r\nbreak", "plain", ""]]);
    expect(out).toBe('a,b,c\r\n"say ""hi""","x,y",\r\n"line\r\nbreak",plain,');
  });

  it("counts the cells it will prefix, so a surface can say so", () => {
    expect(formulaCellCount(["=x", "y"], [["=1", "-5"], ["@a", "b"]])).toBe(3);
    expect(formulaCellCount(["a"], [[1], ["-2"]])).toBe(0);
  });
});

describe("toTsv — the clipboard", () => {
  it("is left as the cell's own text: a copied value is pasted into editors and chats, not only sheets", () => {
    expect(toTsv(["a"], [["=1+1"]])).toBe("a\n=1+1");
  });
});
