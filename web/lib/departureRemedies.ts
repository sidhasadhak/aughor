/**
 * What a reader can DO about a departure the gate held — the remedy beside the verdict.
 *
 * The gate (aughor/govern/departure.py, laws 1–8) says why a message did not leave, in the
 * guard's own words. A reader who meets that sentence alone hits a wall (the user, 2026-09-25:
 * "user needs to know where to troubleshoot such issues.. otherwise its a wall that it hits").
 * This table adds, per guard: what the hold MEANS in the reader's words, what to change, and
 * which screen holds the fix. Nothing here sends — a hold is a verdict, and the next run
 * departs fresh. ONE place for the words, so the departures screen and Spotlight's Guide
 * (§3.11, SP-15) read the same text; the wave moves it server-side beside the laws.
 */
export type RemedyDoor = "automation" | "analysis" | "semantic" | "ask";

export interface Remedy {
  /** What the hold means, in the reader's words. */
  meaning: string;
  /** What to change, and that the next run is the send. */
  action: string;
  /** The screens that hold the fix, in the order to try them. */
  doors: RemedyDoor[];
}

/** The sentence every held row leads with — the wall, named. */
export const HOLD_LEAD =
  "Nothing on this row sends the message: a hold is a verdict. Fix the cause below and run "
  + "the automation again — the next run departs fresh.";

const REMEDIES: Record<string, Remedy> = {
  remeasure: {
    meaning: "The message states numbers the analysis never measured. Only measured numbers "
      + "leave the platform, and a figure the writer computed from measured ones is not one of them.",
    action: "Have the analysis measure what the message should cite — ask for it in the "
      + "automation's question — or have the writer quote only figures from the results. Then "
      + "run the automation again.",
    doors: ["automation", "analysis", "ask"],
  },
  definition: {
    meaning: "A number is stated with no approved metric behind it on this connection.",
    action: "Approve a metric that defines it in the Semantic Layer; the next run cites it.",
    doors: ["semantic", "ask"],
  },
  trust: {
    meaning: "The analysis flagged its own headline figure as a computation error. On screen that "
      + "flag is honesty; in a channel it would be a wrong number with a disclaimer.",
    action: "Open the analysis and read what the check caught; fix the question or the data it "
      + "read, then run again.",
    doors: ["analysis", "ask"],
  },
  caveat: {
    meaning: "The measurement carries a caveat that refutes its own number.",
    action: "Read the caveat on the analysis; the figure cannot leave until the population "
      + "behind it is right.",
    doors: ["analysis", "ask"],
  },
  tie_out: {
    meaning: "A governed metric the message asserts failed its own quality tests at the gate.",
    action: "Open the metric in the Semantic Layer and read which test failed.",
    doors: ["semantic", "ask"],
  },
  freshness: {
    meaning: "The data behind a governed metric is older than the freshness its owner declared.",
    action: "Refresh the source, or revisit the metric's freshness SLA in the Semantic Layer.",
    doors: ["semantic", "ask"],
  },
  claims: {
    meaning: "A sentence makes a causal, associational or forecast claim the analysis did not license.",
    action: "Reword the automation's question or instruction to state the fact; the reader "
      + "draws the conclusion.",
    doors: ["automation", "ask"],
  },
  disagreement: {
    meaning: "Two readings of a metric disagree, and nobody at departure could choose.",
    action: "Choose a reading above. The choice is remembered, and the next run binds it.",
    doors: ["ask"],
  },
  repeat: {
    meaning: "The same message went to the same place within the last seven days, and its "
      + "numbers barely moved.",
    action: "Nothing to fix. It sends again when the numbers move or the window passes.",
    doors: [],
  },
  probation: {
    meaning: "A new automation reaches only the person who declared it until its measured "
      + "precision graduates it.",
    action: "Mark its departures above; it graduates at the measured precision.",
    doors: [],
  },
};

/** The remedy for a guard that held or asked; null for a guard this table does not know. */
export function remedyFor(guard: string): Remedy | null {
  return REMEDIES[guard] ?? null;
}
