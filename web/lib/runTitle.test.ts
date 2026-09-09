/**
 * PX-1 — the run-title deriver. The grounding blocks are byte-for-byte what
 * `aughor/automations/temporal.py` emits (observation_note / previous_report_note);
 * these fixtures are copied from there, and a failure here after a backend edit is
 * the tripwire that says "update both together".
 */
import { describe, expect, it } from "vitest";

import { runDisplayTitle } from "@/lib/runTitle";

const OBS =
  "[Scheduled-run context — written by code, not inferred]\n" +
  "This is a scheduled daily run at 2026-09-09T09:04Z.\n" +
  "Observe 2026-09-01 (UTC), the most recent complete day given this automation's " +
  "observation lag of 8 days — periods younger than that are configured as not yet " +
  "reliable for this source.\n" +
  "Never treat the current, in-progress period (today is 2026-09-09 UTC and it is " +
  "partial by construction) as an observation period, and never compare a partial " +
  "period against a complete one.";

const PREV =
  "[Previous scheduled report — for consistency checking]\n" +
  "The previous run of this automation (2026-09-08T09:04Z) reported:\n" +
  "\"Order volume rose 141.1% above the historical mean.\n\nA second paragraph, " +
  "because a summary may contain blank lines.\"\n" +
  "If your current measurements DISAGREE with numbers that report states for the " +
  "same periods, the SOURCE has restated its own history — say that explicitly, " +
  "with both values, instead of narrating the difference as a business change.";

const QUESTION = "How did order volume move, and is anything anomalous?";

describe("runDisplayTitle", () => {
  it("a plain question passes through untouched", () => {
    expect(runDisplayTitle(QUESTION)).toEqual({ title: QUESTION, scheduled: false });
  });

  it("strips the observation note and keeps the human question", () => {
    expect(runDisplayTitle(`${OBS}\n\n${QUESTION}`))
      .toEqual({ title: QUESTION, scheduled: true });
  });

  it("strips both blocks even when the quoted summary contains blank lines", () => {
    expect(runDisplayTitle(`${OBS}\n\n${PREV}\n\n${QUESTION}`))
      .toEqual({ title: QUESTION, scheduled: true });
  });

  it("a grounded dispatch with an empty question is named, not blank", () => {
    expect(runDisplayTitle(`${OBS}\n\n`))
      .toEqual({ title: "Scheduled run", scheduled: true });
  });

  it("no bracketed title ever survives derivation", () => {
    for (const q of [QUESTION, `${OBS}\n\n${QUESTION}`, `${OBS}\n\n${PREV}\n\n${QUESTION}`, `${OBS}\n\n`]) {
      expect(runDisplayTitle(q).title.startsWith("[")).toBe(false);
    }
  });

  it("null and empty are safe", () => {
    expect(runDisplayTitle(null)).toEqual({ title: "", scheduled: false });
    expect(runDisplayTitle("")).toEqual({ title: "", scheduled: false });
  });
});
