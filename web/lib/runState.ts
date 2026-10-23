/**
 * How a run's end is SAID (the Olist study, Gap 20, 2026-10-22). The kernel records a run its budget stopped as
 * CANCELLED — the word a person's Stop gets — and keeps the cause in its error ("budget exceeded: token budget
 * (200,000 tokens)"). A reader is told which: a budget stop is "stopped at its budget", never "cancelled".
 */

/** True when a run ended because its budget ran out, as the kernel words it. */
export function isBudgetStop(error?: string | null): boolean {
  return /^budget exceeded:/i.test((error ?? "").trim());
}

/** The state a run is SAID to be in: the kernel's, except a budget stop, which is its own. */
export function saidState(state: string, error?: string | null): string {
  return state === "CANCELLED" && isBudgetStop(error) ? "BUDGET_STOP" : state;
}
