import { describe, expect, it } from "vitest";

import { CONNECTOR_TYPES } from "@/lib/connectors.gen";
import { brandMark } from "./brandMarks";

/** No open mark is held for these, and a letter on the tile beats someone else's logo. */
const LETTER_TILES = new Set(["greenplum", "tidb", "starrocks", "doris", "starburst", "alloydb"]);
/** The drawn ones `BrandLogos.tsx` has as its own. */
const DRAWN = new Set(["duckdb", "motherduck", "exasol", "local_upload", "federated"]);

describe("every tile's logo", () => {
  it.each(CONNECTOR_TYPES)("%s has its mark, or is known to go without", type => {
    if (DRAWN.has(type)) return;
    expect(!!brandMark(type)).toBe(!LETTER_TILES.has(type));
  });

  it("an engine with its own mark does not wear its parent's", () => {
    expect(brandMark("aurora_postgres")).toBe(brandMark("aurora_mysql"));
    expect(brandMark("aurora_postgres")).not.toBe(brandMark("postgres"));
    expect(brandMark("athena")).not.toBe(brandMark("s3"));
    expect(brandMark("synapse")).toBe(brandMark("azure"));
  });
});
