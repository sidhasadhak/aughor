/**
 * Security & Audit folds its checks (CLARITY.md: "say a thing once; fold repeats into a count") and names the
 * platform's own flagged reads as noise. Measured 2026-10-10: ~477 identical "query safe" rows and 112 "suspicious"
 * flags that were the platform's own schema reads — these tests hold that shape to two rows and a named split.
 */
import { describe, expect, it } from "vitest";

import {
  blockedSince, byCaller, callerText, flagSplit, foldChecks, fromWhom, isPlatformCaller, outcomeOf, type AuditRecord,
} from "./auditFold";

let n = 0;
function rec(over: Partial<AuditRecord>): AuditRecord {
  n += 1;
  return {
    id: `r${n}`, ts: "2026-10-11T23:00:00Z", connection_id: "c1", hypothesis_id: "__brief_period__",
    sql_digest: "SELECT 1", sql_full: "SELECT 1", verdict: "safe", row_count: 3, duration_ms: 600, pii_redacted: 0, error: null,
    ...over,
  };
}

describe("outcomeOf", () => {
  it("reads a verdict and an error as what happened to the statement", () => {
    expect(outcomeOf({ verdict: "blocked", error: "DROP statements are not permitted" })).toBe("blocked");
    expect(outcomeOf({ verdict: "pii_blocked", error: null })).toBe("withheld");
    expect(outcomeOf({ verdict: "suspicious", error: null })).toBe("flagged");
    expect(outcomeOf({ verdict: "safe", error: "Binder Error" })).toBe("failed");
    expect(outcomeOf({ verdict: "safe", error: null })).toBe("passed");
  });
});

describe("isPlatformCaller", () => {
  it("names the platform's own background callers, and never a person's surface or an analysis", () => {
    for (const own of ["__brief_period__", "__trust_coltypes__", "__explorer__", "__monitor__", "profile-calibrate", "cb2_review"]) {
      expect(isPlatformCaller(own)).toBe(true);
    }
    for (const asked of ["query_builder", "query_workbench", "card:abc", "h1", "subq_3", ""]) {
      expect(isPlatformCaller(asked)).toBe(false);
    }
  });

  it("speaks the reader's words for the callers measured on theLook", () => {
    expect(callerText("__brief_period__")).toBe("Briefer · period comparison");
    expect(callerText("__trust_coltypes__")).toBe("Trust check · column types");
    expect(callerText("query_workbench")).toBe("You · SQL Editor");
    // the object door's reads, in words — never its route names (theLook, 2026-10-12: "objects.list", "objects")
    expect(callerText("objects")).toBe("Objects · counted");
    expect(callerText("objects.list")).toBe("Objects · listed");
    expect(callerText("objects.findings_scan")).toBe("Objects · an object's page");
    // an unknown dunder still reads as words, never as a key
    expect(callerText("__some_new_probe__")).toBe("some new probe");
  });
});

describe("foldChecks", () => {
  it("folds 477 checks into two rows: the passed reads and the platform's own flags, each with its count", () => {
    const rows = [
      ...Array.from({ length: 365 }, () => rec({ verdict: "safe" })),
      ...Array.from({ length: 112 }, () => rec({ hypothesis_id: "__trust_coltypes__", verdict: "suspicious", row_count: 0, duration_ms: 0 })),
    ];
    const groups = foldChecks(rows);
    expect(groups).toHaveLength(2);
    // the flags rank above what simply passed, and are marked as the platform's own
    expect(groups[0]).toMatchObject({ outcome: "flagged", own: true, name: "Trust check · column types" });
    expect(groups[0].rows).toHaveLength(112);
    expect(groups[1]).toMatchObject({ outcome: "passed", name: "Briefer · period comparison" });
    expect(groups[1].rows).toHaveLength(365);
  });

  it("puts a refusal and a person's flag before the platform's own, and keeps the newest error's words", () => {
    const groups = foldChecks([
      rec({ verdict: "suspicious" }),
      rec({ hypothesis_id: "query_builder", verdict: "suspicious" }),
      rec({ hypothesis_id: "query_builder", verdict: "blocked", error: "older reason", ts: "2026-10-01T00:00:00Z" }),
      rec({ hypothesis_id: "query_builder", verdict: "blocked", error: "newer reason", ts: "2026-10-02T00:00:00Z" }),
    ]);
    expect(groups.map(g => `${g.outcome}${g.own ? "·own" : ""}`)).toEqual(["blocked", "flagged", "flagged·own"]);
    expect(groups[0].reason).toBe("newer reason");
    expect(groups[0].earliest).toBe("2026-10-01T00:00:00Z");
  });
});

describe("flagSplit and byCaller", () => {
  it("splits flags into the platform's own and everyone else's", () => {
    const person = rec({ hypothesis_id: "query_workbench", verdict: "suspicious" });
    const s = flagSplit([rec({ verdict: "suspicious" }), rec({ verdict: "suspicious" }), person, rec({})]);
    expect(s).toMatchObject({ flagged: 3, own: 2 });
    expect(s.asked).toEqual([person]);
    expect(fromWhom(s.asked)).toBe("You · SQL Editor 1");
  });

  it("counts who ran the checks, most first, folding past six into Other", () => {
    const names = ["__a__", "__b__", "__c__", "__d__", "__e__", "__f__", "__g__"];
    const rows = names.flatMap((h, i) => Array.from({ length: 10 - i }, () => rec({ hypothesis_id: h })));
    const c = byCaller(rows);
    expect(c).toHaveLength(6);
    expect(c[0]).toMatchObject({ name: "a", total: 10 });
    expect(c[5]).toMatchObject({ name: "Other", total: 5 + 4 });
  });
});

describe("blockedSince", () => {
  it("keeps the refusals of the last week only", () => {
    const now = Date.parse("2026-10-12T00:00:00Z");
    const recent = rec({ verdict: "blocked", ts: "2026-10-10T00:00:00Z" });
    expect(blockedSince([recent, rec({ verdict: "blocked", ts: "2026-09-12T00:00:00Z" }), rec({})], now)).toEqual([recent]);
  });
});
