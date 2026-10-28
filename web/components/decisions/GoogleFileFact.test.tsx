// @vitest-environment jsdom
/**
 * A decision's "From Google" field (the decision-framework study §3.2; on when its setup exists, ROADMAP §3.65). While
 * the install has no Google OAuth client, or the reader no grant on the Google Drive comments card, the field says which
 * in its place — never a link box that cannot read. Once nothing is missing, the box and its button are there.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen, waitFor } from "@/lib/testing";

const rec = vi.hoisted(() => ({ readGoogleFileOntoDecision: vi.fn() }));
vi.mock("@/lib/record", async original => ({ ...(await original<typeof import("@/lib/record")>()), ...rec }));

const { GoogleFileFact } = await import("@/components/decisions/DecisionsPanel");

const NO_CLIENT = "Not set up yet: this install has no Google OAuth client. Add it in Operations → Integrations → Google → Set up.";

beforeEach(() => { rec.readGoogleFileOntoDecision.mockReset(); });

describe("the From Google field", () => {
  it("says what is missing in place of the link box", () => {
    render(<GoogleFileFact decisionId="d1" files={["f1"]} missing={NO_CLIENT} onRead={() => {}} />);
    expect(screen.getByTestId("google-file-missing")).toHaveTextContent(NO_CLIENT);
    expect(screen.getByTestId("google-file")).toHaveTextContent("1 file read here");
    expect(screen.queryByLabelText("A Google file's link")).toBeNull();
    expect(screen.queryByRole("button", { name: "Read its comments" })).toBeNull();
  });

  it("offers the link box once nothing is missing, and says what a read found", async () => {
    rec.readGoogleFileOntoDecision.mockResolvedValue({ decision: "d2", file: "f1", read: 2, new: 2, already_held: 0, more: "" });
    const onRead = vi.fn();
    render(<GoogleFileFact decisionId="d1" files={[]} missing="" onRead={onRead} />);
    expect(screen.queryByTestId("google-file-missing")).toBeNull();
    fireEvent.change(screen.getByLabelText("A Google file's link"), { target: { value: "https://docs.google.com/spreadsheets/d/x/edit" } });
    fireEvent.click(screen.getByRole("button", { name: "Read its comments" }));
    await waitFor(() => expect(onRead).toHaveBeenCalledWith("d2"));
    expect(screen.getByTestId("google-file")).toHaveTextContent("2 comments read · 2 new");
  });
});
