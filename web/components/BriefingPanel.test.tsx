/**
 * How the explorer's phase reads to a person.
 *
 * The stored phase is a machine state — `canvas_needs_resume`, `is_unfinished` and the
 * boot recovery all key on it, and none of that changes here. This is only the word and
 * the colour on screen, and it needed changing because the word was doing harm.
 *
 * A run that ends without completing is recorded as `failed` whatever the cause, and the
 * engine's own most common reason is *"cancelled (budget exceeded or stopped) — progress
 * saved"*. Rendering that in red as FAILED overstated what the engine recorded: a live
 * deployment with 54 findings and a grounded briefing read as broken, and the reasonable
 * response to that is to throw the lot away and start again — which is exactly what the
 * user of it proposed doing.
 *
 * The half these tests defend hardest is the half that was NOT softened. A run that ended
 * with nothing behind it still says `failed`, in red. The split is the one already present
 * in the data — did this connection end up with work — so nothing here is a judgement
 * invented to make a number look kinder.
 */
import { describe, expect, it } from "vitest";

import { explorerPhaseLabel } from "@/components/BriefingPanel";

describe("explorerPhaseLabel", () => {
  it("softens a failed run that LEFT WORK BEHIND", () => {
    // The reported case: phase failed, 54 findings, a full briefing on screen.
    expect(explorerPhaseLabel("failed", true)).toEqual({
      text: "incomplete", tone: "warn",
    });
  });

  it("still says FAILED, in red, when nothing survived", () => {
    // The half that must not be softened. Nothing to keep, and it wants attention —
    // here "start afresh" really is the answer, and the word should say so.
    expect(explorerPhaseLabel("failed", false)).toEqual({
      text: "failed", tone: "bad",
    });
  });

  it("leaves a complete run alone", () => {
    expect(explorerPhaseLabel("complete", true)).toEqual({
      text: "complete", tone: "good",
    });
    // A completed run with no findings is still complete — the phase is the truth about
    // the RUN, and softening or hardening it on the strength of its output would be this
    // function overreaching.
    expect(explorerPhaseLabel("complete", false)).toEqual({
      text: "complete", tone: "good",
    });
  });

  it("passes a mid-run phase through untouched", () => {
    // These are transient and self-explanatory; renaming them would only make the header
    // disagree with the logs, which use the phase verbatim.
    for (const phase of ["domain_intel", "synthesis", "null_meaning", "pending"]) {
      expect(explorerPhaseLabel(phase, true)).toEqual({ text: phase, tone: "busy" });
    }
  });

  it("says 'unknown' rather than rendering nothing when there is no status", () => {
    // A blank where a status belongs reads as a broken component; "unknown" reads as an
    // answer. The control bar has its own separate handling for a missing status.
    expect(explorerPhaseLabel(undefined, false)).toEqual({
      text: "unknown", tone: "busy",
    });
  });

  it("keys the softening on WORK, not on the phase alone", () => {
    // The whole design in one assertion: the same phase reads two ways, and what decides
    // is whether anything survived the run.
    const withWork = explorerPhaseLabel("failed", true);
    const without = explorerPhaseLabel("failed", false);
    expect(withWork.text).not.toBe(without.text);
    expect(withWork.tone).not.toBe(without.tone);
  });
});
