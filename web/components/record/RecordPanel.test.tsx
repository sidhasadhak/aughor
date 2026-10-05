// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Connection } from "@/lib/api";
import type { Claim, ClaimCrossLink } from "@/lib/record";

import { RecordPanel } from "./RecordPanel";

const record = vi.hoisted(() => ({ getClaim: vi.fn(), getClaimVersions: vi.fn(), getClaimCrossLinks: vi.fn() }));
vi.mock("@/lib/record", async (original) => ({ ...(await original<typeof import("@/lib/record")>()), ...record }));

const CONNECTIONS = [{ id: "shop", name: "The shop" }, { id: "crm", name: "The CRM" }] as unknown as Connection[];

const claim = (extra: Partial<Claim> = {}): Claim => ({
  id: "c1", key: "claim:c1", version: 1, kind: "finding", about: { kind: "connection", key: "shop" },
  statement: { text: "Orders fell 4% in September", metric: "", value: null, unit: "", range_start: "", range_end: "", object_set: "" },
  tier: "measured", status: "Final", state: "", as_of: "2026-10-05", owner: "", author: "agent:explorer", author_kind: "agent",
  warrants: [], falsifier: "", superseded_by: "", extra: {}, relied_on_by: [], told: [], told_note: "", ...extra,
} as unknown as Claim);

const LINK: ClaimCrossLink = {
  domain: "default", relationship: "Order_RELATES_TO_Account", name: "order placed by account", near_type: "Order",
  far_type: "Account", far_connection: "crm", cardinality: "N:1", withheld: false, far_claims_total: 7,
  far_claims: [{ id: "far-1", text: "Enterprise accounts renew at 91%", kind: "finding", tier: "measured", status: "Final", as_of: "2026-10-01" }],
};

const show = (onInspectClaim = vi.fn()) => {
  render(<RecordPanel connections={CONNECTIONS} selectedConn="shop" openId="c1" onOpen={() => undefined}
    onOpenDecision={() => undefined} onInspectClaim={onInspectClaim} onOpenRun={() => undefined}
    onOpenReceipt={() => undefined} onOpenDefinitions={() => undefined} onOpenMap={() => undefined} />);
  return onInspectClaim;
};

beforeEach(() => {
  for (const f of Object.values(record)) f.mockReset();
  record.getClaimVersions.mockResolvedValue([]);
  record.getClaim.mockResolvedValue(claim());
});

describe("a claim's page cites links into other connections", () => {
  it("names the link, the far connection and its newest claims, which open beside the page", async () => {
    record.getClaimCrossLinks.mockResolvedValue([LINK]);
    const inspect = show();
    expect(await screen.findByText("Linked in other connections")).toBeInTheDocument();
    expect(screen.getByText("Order is linked to Account, in The CRM")).toBeInTheDocument();
    expect(screen.getByText("the newest 1 of 7 claims about Account there")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Enterprise accounts renew at 91%" }));
    expect(inspect).toHaveBeenCalledWith("far-1");
  });

  it("says a far connection the reader may not see is withheld, and names nothing of it", async () => {
    record.getClaimCrossLinks.mockResolvedValue([{ ...LINK, withheld: true, far_type: "", far_connection: "", far_claims: [], far_claims_total: 0 }]);
    show();
    expect(await screen.findByText("Order is linked to a type in a connection you may not see.")).toBeInTheDocument();
    expect(screen.queryByText(/Account/)).toBeNull();
  });

  it("has no such section for a claim tied to no link, and says so when the ontology could not be read", async () => {
    record.getClaimCrossLinks.mockResolvedValue([]);
    const first = render(<RecordPanel connections={CONNECTIONS} selectedConn="shop" openId="c1" onOpen={() => undefined}
      onOpenDecision={() => undefined} onOpenRun={() => undefined} onOpenReceipt={() => undefined}
      onOpenDefinitions={() => undefined} onOpenMap={() => undefined} />);
    expect(await screen.findByText("Who else was told")).toBeInTheDocument();
    expect(screen.queryByText("Linked in other connections")).toBeNull();
    first.unmount();
    expect(record.getClaimCrossLinks).toHaveBeenCalledWith("c1");            // asked of the ontology's own door
    record.getClaimCrossLinks.mockRejectedValue(new Error("The organisation's ontology could not be read (500)"));
    show();
    expect(await screen.findByText(/could not be read just now, so no link is listed/)).toBeInTheDocument();
  });
});
