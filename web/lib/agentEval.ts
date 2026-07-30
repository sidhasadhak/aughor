/**
 * Wave H6 — how an agent's golden-suite pass chip is allowed to be rendered.
 *
 * The chip used to read `goldens 5/5` forever. It survived every edit, so an agent whose
 * instructions had been inverted and whose document scope had been emptied still showed a
 * green pass earned by a configuration that no longer existed. The backend now labels the
 * chip (`eval_basis`) instead of deleting it — the old number is real evidence about a real
 * configuration, and destroying it would lose what the agent used to be able to do.
 *
 * This lives in one place because the chip renders on two surfaces (the persona roster and
 * the fleet table) and a rule enforced by two hand-written copies is a rule that drifts.
 */

export type EvalBasis = "none" | "current" | "stale" | "unknown";

export interface AgentEval {
  passed: number;
  total: number;
  at?: string;
}

export interface EvalChip {
  /** Chip text, e.g. "goldens 5/5 · stale". Null when there is nothing measured to show. */
  label: string;
  /** Design-system hue. Never `positive` unless the number is about the agent as it is now. */
  hue: "positive" | "caution" | "muted";
  /** Why the chip reads the way it does — belongs on the element's title/tooltip. */
  detail: string;
}

/**
 * The chip for one agent, or null when it has never been evaluated.
 *
 * `stale` and `unknown` deliberately do NOT hide the number. Hiding it would answer
 * "how good is this agent?" with silence, when the honest answer is "it scored 5/5, but
 * not as it is configured now".
 */
export function evalChip(
  lastEval: AgentEval | null | undefined,
  basis: EvalBasis | undefined,
): EvalChip | null {
  if (!lastEval || !lastEval.total) return null;
  const score = `goldens ${lastEval.passed}/${lastEval.total}`;

  switch (basis) {
    case "current":
      return {
        label: score,
        hue: "positive",
        detail: "Measured against this agent's current configuration.",
      };
    case "stale":
      return {
        label: `${score} · stale`,
        hue: "caution",
        detail:
          "Earned before this agent was edited — the score describes a different " +
          "configuration. Re-run the golden suite to re-earn it.",
      };
    case "unknown":
      return {
        label: `${score} · unverified`,
        hue: "muted",
        detail:
          "Recorded before Aughor tracked which configuration a score belongs to, so it " +
          "cannot be shown as current or stale. Re-run the golden suite to settle it.",
      };
    default:
      // No basis reported (an older API, or a surface that does not send one). Show the
      // number without a verdict rather than inventing one.
      return { label: score, hue: "muted", detail: "" };
  }
}
