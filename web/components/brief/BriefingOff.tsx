/**
 * The Briefing of a scope a person turned off: one line saying so, who turned it off, and the way back on.
 * Nothing found before it was turned off is shown or written from — on LuxExperience (2026-10-11) all three
 * schemas were off and a rebuilt Briefing still synthesised their leftover findings.
 */
import { Button } from "@/components/ui/button";
import type { BriefingOff } from "@/lib/api";
import { requestTab } from "@/lib/navigate";

const REASON_WORDS: Record<string, string> = {
  system_table: "system tables",
  deprecated: "deprecated",
  out_of_domain: "not this business's data",
  sensitive: "sensitive",
};

export function BriefingOffNotice({ off, connectionId }: { off: BriefingOff; connectionId: string }) {
  const meta = [
    off.declared_by ? `Turned off by ${off.declared_by}` : "",
    REASON_WORDS[off.reason] ? `Marked ${REASON_WORDS[off.reason]}` : "",
  ].filter(Boolean).join(" · ");
  return (
    <div role="status" data-testid="briefing-off"
      style={{ background: "var(--bg-1)", borderRadius: "var(--r3)", padding: "16px 18px",
               display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
      <div style={{ flex: 1, minWidth: 240 }}>
        <div className="aug-fs-chrome" style={{ color: "var(--t1)" }}>{off.said}</div>
        {meta && <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 4 }}>{meta}</div>}
      </div>
      <Button size="xs" variant="secondary" onClick={() => requestTab("catalog", { conn: connectionId })}>
        Turn it on in the Catalog
      </Button>
    </div>
  );
}
