import { describe, expect, it } from "vitest";

import { answerSays, type ObjectCompleteness } from "./objects";

const read = (state: ObjectCompleteness["state"], said = ""): ObjectCompleteness =>
  ({ state, shown: 500, of: null, withheld: [], masked: [], said, took_ms: 12 });

describe("answerSays — what a piece says of an object query's answer (ED-6)", () => {
  it("says a read cut at the connection's cap, after its caveats", () => {
    expect(answerSays({ caveats: ["a caveat"], completeness: read("truncated", "the first 500 rows — there are more") }))
      .toEqual(["a caveat", "the first 500 rows — there are more"]);
  });

  it("adds nothing for a complete or a withheld read: a row policy's words are already caveats", () => {
    expect(answerSays({ caveats: ["only some orders are shown"], completeness: read("withheld", "only some orders are shown") }))
      .toEqual(["only some orders are shown"]);
    expect(answerSays({ caveats: [], completeness: read("complete") })).toEqual([]);
  });

  it("a server from before completeness says its caveats as before", () => {
    expect(answerSays({ caveats: ["a caveat"] })).toEqual(["a caveat"]);
    expect(answerSays({})).toEqual([]);
  });
});
