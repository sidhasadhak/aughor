// @vitest-environment jsdom
/**
 * The Briefing of a schema turned off says so, who turned it off, and the way back on (2026-10-11: LuxExperience's
 * three schemas were off and a rebuilt Briefing still synthesised what was found before).
 */
import { fireEvent, render, screen } from "@/lib/testing";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/useMe", () => ({ useMe: () => ({ actor: "amit" }) }));

import { BriefingOffNotice } from "@/components/brief/BriefingOff";
import { NAVIGATE_EVENT } from "@/lib/navigate";

const OFF = { schemas: ["gold_finance"], reason: "out_of_domain", declared_by: "amit",
              said: "gold_finance is turned off for analysis, so no Briefing is written for it." };

describe("a Briefing of a schema turned off", () => {
  it("says it is off, by whom (“you” for the reader) and marked how, in one line and its meta", () => {
    render(<BriefingOffNotice off={OFF} connectionId="dcc63d83" />);
    expect(screen.getByRole("status")).toHaveTextContent(OFF.said);
    expect(screen.getByText("Turned off by you · Marked not this business's data")).toBeInTheDocument();
  });

  it("names someone else by their name", () => {
    render(<BriefingOffNotice off={{ ...OFF, declared_by: "ana" }} connectionId="dcc63d83" />);
    expect(screen.getByText(/^Turned off by ana/)).toBeInTheDocument();
  });

  it("leaves out what it was not told", () => {
    render(<BriefingOffNotice off={{ ...OFF, declared_by: "", reason: "other" }} connectionId="dcc63d83" />);
    expect(screen.queryByText(/Turned off by|Marked/)).toBeNull();
  });

  it("opens the Catalog on the connection to turn it back on", () => {
    const heard = vi.fn();
    window.addEventListener(NAVIGATE_EVENT, heard as EventListener);
    render(<BriefingOffNotice off={OFF} connectionId="dcc63d83" />);
    fireEvent.click(screen.getByRole("button", { name: "Turn it on in the Catalog" }));
    expect((heard.mock.calls[0][0] as CustomEvent).detail).toEqual({ tab: "catalog", params: { conn: "dcc63d83" } });
    window.removeEventListener(NAVIGATE_EVENT, heard as EventListener);
  });
});
