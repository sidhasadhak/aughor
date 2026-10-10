// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { columnsOffered } from "@/components/cockpit/OntologyPieceComposer";
import type { DeclaredAction } from "@/lib/objects";

const action = (id: string, params: DeclaredAction["params"], edits: DeclaredAction["edits"]): DeclaredAction => ({
  id, display_name: id, description: "", entity: "", object_type: "return", kind: "annotate", risk: "low", params, edits,
});
const param = (name: string, kind: "value" | "object", object_type = "") =>
  ({ name, display_name: name, data_type: "VARCHAR", required: true, default_value: null, kind, object_type, description: "" });

describe("the columns a table of returns may list", () => {
  it("offers what an action writes on the return, never what it writes on the case it opens", () => {
    // found on Lux (2026-10-10): a return's table offered the case's about, status and assignee as the return's
    const actions = {
      escalate: action("escalate", [param("return", "object", "return")],
                       [{ object: "return", property: "escalated_to_refunds", value: "yes", note: "" }]),
      open_case: action("open_case", [param("return", "object", "return"), param("assignee", "value")],
                        [{ object: "created", property: "about", value: "{return}", note: "" },
                         { object: "created", property: "status", value: "open", note: "" }]),
    };
    const type = { id: "Return", properties: [
      { name: "return_id", display_name: "Return Id", is_key: true }, { name: "carrier", display_name: "Carrier", is_key: false },
    ] } as unknown as Parameters<typeof columnsOffered>[0];
    expect(columnsOffered(type, actions).map(c => [c.name, c.edited])).toEqual([["carrier", false], ["escalated_to_refunds", true]]);
  });
});
