/**
 * jobKinds.ts — a run's kind and title in words a person reads.
 *
 * The jobs API titles a run by its question when it has one; otherwise an exploration is
 * `Exploring <connection id>` and anything else is its kind, a frozen slug (`alert_proposals`).
 * Both reached Agent Ops' run lists as they were. The slug and the id are keys the platform
 * composes for itself (lib/names.ts' law); this module turns them into names, and the raw
 * value stays for the row's hover.
 *
 * The keys below are the backend's frozen job kinds (docs/GLOSSARY.md, "Names that are frozen")
 * — spelled as the wire spells them, because a renamed key would match nothing.
 */
import { connectionLabel, keyToWords } from "@/lib/names";
import { runDisplayTitle } from "@/lib/runTitle";

const JOB_KIND_WORDS: Record<string, string> = {
  exploration: "Exploration",
  explain_move: "Explaining a metric's move",
  investigation: "Deep analysis",
  investigation_salvage: "Finishing a deep analysis a restart cut off",
  monitor: "Monitor check",
  alert_proposals: "Proposing alerts",
  brief: "Briefing",
  profile: "Profiling the data",
  automation: "Automation run",
  eval_experiment: "Eval experiment",
};

/** A job kind as a phrase. A kind this map does not know still reads as words, never as a slug. */
export function jobKindLabel(kind: string | null | undefined): string {
  const k = (kind ?? "").trim();
  if (JOB_KIND_WORDS[k]) return JOB_KIND_WORDS[k];
  const words = keyToWords(k);
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Run";
}

/** What a run is called on a list, and the raw title the API sent (for the hover). */
export function jobTitle(
  job: { kind: string; title: string | null | undefined; conn_id: string | null; canvas_id: string | null },
  connections: ReadonlyArray<{ id: string; name: string }>,
): { title: string; raw: string } {
  const raw = (job.title || job.kind || "").trim();
  if (!raw || raw === job.kind) return { title: jobKindLabel(job.kind), raw };
  if (job.kind === "exploration") {
    const on = job.conn_id ? connectionLabel(job.conn_id, connections) : "";
    if (job.canvas_id && raw === `Exploring ${job.canvas_id}`) {
      return { title: on ? `Exploring a canvas on ${on}` : "Exploring a canvas", raw };
    }
    if (job.conn_id && raw === `Exploring ${job.conn_id}`) return { title: `Exploring ${on}`, raw };
  }
  return { title: runDisplayTitle(raw).title, raw };
}
