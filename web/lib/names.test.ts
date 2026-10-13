/**
 * Who did something, said to the reader: their own name reads as "you" — "Proposed by you", never their login back
 * at them. `me` is the name the server records the reader under (`useMe().actor`); the ledger writes `user:<name>`.
 */
import { describe, expect, it } from "vitest";

import { whoLabel } from "./record";
import { byWho } from "./names";

describe("byWho", () => {
  it("says 'you' for the reader, with or without the ledger's prefix, and anyone else by name", () => {
    expect(byWho("amit", "amit")).toBe("you");
    expect(byWho("user:amit", "amit")).toBe("you");
    expect(byWho("ana", "amit")).toBe("ana");
    // Until the server has said who is reading, nobody is "you".
    expect(byWho("amit", null)).toBe("amit");
    expect(byWho("", "")).toBe("");
  });

  it("is what the ledger's words use when they are told who is reading", () => {
    expect(whoLabel("user:amit", "amit")).toBe("you");
    expect(whoLabel("amit", "amit")).toBe("you");
    expect(whoLabel("user:ana", "amit")).toBe("ana");
    expect(whoLabel("user:amit")).toBe("amit");
    expect(whoLabel("agent:amit", "amit")).toBe("the amit agent");
    expect(whoLabel("system", "system")).toBe("the platform");
  });
});
