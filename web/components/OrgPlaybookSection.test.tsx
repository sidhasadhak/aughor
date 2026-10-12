// @vitest-environment jsdom
/**
 * The playbook, moved to Settings ▸ Organization (2026-09-19, the user's call).
 *
 * What these guard is the honesty of the move, not the move itself: a capability that
 * stops being a nav door must still announce itself where it landed, and a list that
 * hides 55% of its rows must say so. Both are DS-17b's lesson one screen over — a reader
 * who cannot see something must still learn it exists.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrgPlaybookSection } from "@/components/OrgPlaybookSection";

const ENTRIES = [
  ...Array.from({ length: 6 }, (_, i) => ({ tags: ["data quality"], id: `dq${i}` })),
  ...Array.from({ length: 4 }, (_, i) => ({ tags: ["customer retention"], id: `p${i}` })),
];

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ENTRIES })));
});

describe("the playbook in Settings", () => {
  it("states how many plays there are and where they came from", async () => {
    render(<OrgPlaybookSection />);
    // The count IS the answer to "what do we have", so it shows without expanding — at the card label's right end
    // since the CLARITY redo (2026-10-12), with where they came from on the line under it.
    expect(await screen.findByText("10 plays")).toBeInTheDocument();
    expect(screen.getByText("From your installed industry packages")).toBeInTheDocument();
  });

  it("names the rule-outs it is not listing, and says where they run", async () => {
    render(<OrgPlaybookSection />);
    // Silently dropping 6 of 10 rows would be the defect this filter exists to avoid. Said as a chip now: the count
    // and who runs them, with the rest of the sentence on hover.
    expect(await screen.findByText(/6 data-quality rule-outs, run by the Verifier/)).toBeInTheDocument();
    expect(screen.getByTitle(/The Verifier runs these during a deep report/)).toBeInTheDocument();
    expect(screen.getByText(/4 read when a run’s numbers match/)).toBeInTheDocument();
  });

  it("is collapsed until asked", async () => {
    render(<OrgPlaybookSection />);
    const toggle = await screen.findByTestId("org-playbook-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("a count that cannot be read states NOTHING rather than zero", async () => {
    // "0 plays" is a claim about the organisation; a failed fetch is a claim about the
    // network. They must not render alike.
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    render(<OrgPlaybookSection />);
    await waitFor(() => expect(screen.getByTestId("org-playbook-toggle")).toBeInTheDocument());
    expect(screen.queryByText(/0 plays/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^[\d,]+ plays$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/From your installed/)).not.toBeInTheDocument();
  });
});
