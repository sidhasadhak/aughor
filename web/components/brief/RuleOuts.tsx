"use client";
/**
 * Rule out first — IP-1. The known ways a reported move can be the data rather than the business: the
 * playbook's data-quality checks for the metric in the direction it moved (read high when it rose, low
 * when it fell), each with its fix. Nothing here was run against the data, and the lead line says so in
 * the words the backend sent (`aughor/playbook/rule_outs.py`) — a list without that note would read as
 * findings, so a payload without its lead still shows the note. Rendered before the recommended
 * actions; absent when the report states no move.
 */
import { BriefSection } from "@/components/brief/Brief";
import type { RuleOuts } from "@/lib/types";

export function RuleOutsSection({ ruleOuts }: { ruleOuts?: RuleOuts | null }) {
  if (!ruleOuts?.items?.length) return null;
  return (
    <BriefSection label="Rule out first" className="border-t border-zinc-800/60 pt-4">
      <p className="aug-fs-ui text-zinc-500 leading-relaxed">
        {ruleOuts.lead || ruleOuts.note || "Not checked against your data."}
      </p>
      <ul className="flex flex-col gap-2.5">
        {ruleOuts.items.map(item => (
          <li key={item.play_id} className="flex gap-2">
            <span className="shrink-0 text-zinc-500 select-none mt-px">•</span>
            <div className="flex flex-col gap-0.5 min-w-0">
              <span className="aug-text-ui text-zinc-200 leading-relaxed">{item.cause}</span>
              {item.fix && <span className="aug-fs-ui text-zinc-500 leading-relaxed">Fix: {item.fix}</span>}
            </div>
          </li>
        ))}
      </ul>
    </BriefSection>
  );
}
