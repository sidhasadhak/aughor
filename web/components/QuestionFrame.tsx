"use client";

/**
 * ON-10 — the question's frame, shown with the answer.
 *
 * Before a deep analysis reads a question, its business terms are resolved against the DECLARED ontology — a
 * promise, the lag between two stages, a rule, the moment a stage is reached — and the analysis starts from the type
 * the definition is kept per, testing the drivers the declared links reach (`aughor/ontology/framing.py`). This block
 * says what each word was read as, so a reader can see — and challenge — the definition the numbers below were
 * computed under. It renders nothing when the question reached nothing declared.
 */

import type { OntologyFrame } from "@/lib/types";
import { BriefDetails, BriefDetailBlock } from "@/components/brief/Brief";

export function QuestionFrame({ frame }: { frame?: OntologyFrame | null }) {
  if (!frame || !frame.defines || !frame.reading) return null;
  const chosen = frame.chosen != null ? frame.outcomes[frame.chosen] ?? null : null;
  const candidates = frame.outcomes.filter((o) => o.usable);
  const rules = frame.rules.filter((r) => r.usable);
  const unapplied = frame.rules.filter((r) => !r.usable && r.why_not);
  const drivers = [...frame.drivers.filter((d) => d.named), ...frame.drivers.filter((d) => !d.named)];

  return (
    <section className="flex flex-col gap-1.5" data-testid="question-frame">
      <div className="aug-label">Read as</div>
      <p className="aug-fs-sm text-zinc-300 leading-relaxed">{frame.reading}</p>
      {frame.chosen_by === "model" && candidates.length > 1 && (
        <p className="aug-fs-xs text-zinc-500">
          The words fit {candidates.length} declared definitions ({candidates.map((c) => c.name).join(", ")}); a model
          chose this one.
        </p>
      )}
      <BriefDetails summary="How the question was framed">
        {chosen && (
          <BriefDetailBlock label="Definition">
            <p className="aug-fs-xs text-zinc-300">{chosen.label}</p>
            <p className="aug-fs-xs text-zinc-400">{chosen.definition}</p>
            {chosen.measured && <p className="aug-fs-xs text-zinc-500">Measured: {chosen.measured}</p>}
          </BriefDetailBlock>
        )}
        {rules.length > 0 && (
          <BriefDetailBlock label="Rules">
            {rules.map((r) => (
              <p key={r.id} className="aug-fs-xs text-zinc-400">
                {r.id}: {r.words}
                {r.via ? ` (through ${r.via})` : ""}
              </p>
            ))}
          </BriefDetailBlock>
        )}
        {frame.moments.length > 0 && (
          <BriefDetailBlock label="Moments">
            {frame.moments.map((m) => (
              <p key={`${m.process}.${m.stage}`} className="aug-fs-xs text-zinc-400">
                {m.stage} of {m.process_label}: {m.timestamp}
              </p>
            ))}
          </BriefDetailBlock>
        )}
        {frame.start && (
          <BriefDetailBlock label="Started from">
            <p className="aug-fs-xs text-zinc-400">
              {frame.start.name}
              {frame.start.table ? ` (${frame.start.table})` : ""}
            </p>
          </BriefDetailBlock>
        )}
        {drivers.length > 0 && (
          <BriefDetailBlock label="Drivers the declared links reach">
            {drivers.map((d) => (
              <p key={d.path} className="aug-fs-xs text-zinc-400">
                {d.path}
                {d.named ? " · named in the question" : ""}
              </p>
            ))}
          </BriefDetailBlock>
        )}
        {(unapplied.length > 0 || frame.notes.length > 0) && (
          <BriefDetailBlock label="Notes">
            {unapplied.map((r) => (
              <p key={r.id} className="aug-fs-xs text-zinc-500">
                {r.id} was not applied: {r.why_not}
              </p>
            ))}
            {frame.notes.map((n) => (
              <p key={n} className="aug-fs-xs text-zinc-500">{n}</p>
            ))}
          </BriefDetailBlock>
        )}
      </BriefDetails>
    </section>
  );
}
