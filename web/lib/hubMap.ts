/** HB-6 — pure shaping for the hub map's cells. Kept out of the component (the
 *  AgentMap rule): anything a test must catch lives in a function that needs no DOM. */
import type { HubCost, HubDestination, HubProbation } from "@/lib/api";

/** One phrase per destination — what a reader scans, with the raw ids left to titles. */
export function destinationText(d: HubDestination): string {
  if (d.routed_about) {
    const n = d.resolved?.length ?? 0;
    return `routed(${d.routed_about}) → ${n} ${n === 1 ? "destination" : "destinations"}`;
  }
  if (d.kind === "slack_post") return `slack ${d.channel || d.target}`;
  if (d.kind === "notify") {
    return d.label ? `${d.label} (${d.type || "trigger"})` : `trigger ${d.target}`;
  }
  return d.target ? `${d.kind} ${d.target}` : d.kind;
}

export function tokensText(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M tok`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k tok`;
  return `${n} tok`;
}

/** The cost cell. "—" when the window saw nothing; otherwise dollars when any were
 *  priced, tokens always. The caveat rides separately (`costCaveat`) so the cell stays
 *  scannable and the honesty lands in the title. */
export function costText(c: HubCost): string {
  if (!c.runs && !c.total_tokens) return "—";
  const parts: string[] = [];
  if (c.cost_usd > 0) parts.push(`$${c.cost_usd.toFixed(c.cost_usd < 0.1 ? 4 : 2)}`);
  parts.push(tokensText(c.total_tokens));
  return parts.join(" · ");
}

/** Why the cost is a floor, when it is one. "" when nothing was unpriced. */
export function costCaveat(c: HubCost): string {
  const bits: string[] = [];
  if (c.unpriced_calls) bits.push(`${c.unpriced_calls} calls with no published rate`);
  if (c.calls_without_usage) bits.push(`${c.calls_without_usage} calls that reported no usage`);
  if (!bits.length) return "";
  return `${bits.join(", ")} — a floor, not a total`;
}

/** The probation cell: graduated chains say so; an unmeasured precision is "not
 *  measured", never 0%. The denominator includes unlanded pushes (HB-2's law: a push
 *  that earns no landing is not value). */
export function probationText(p: HubProbation): string {
  if (!p.on) return p.marked ? "graduated" : "—";
  if (p.precision === null) return "probation · not measured";
  const denom = p.marked + p.unlanded;
  return `probation · ${Math.round(p.precision * 100)}% of ${denom}`;
}

export function probationDetail(p: HubProbation): string {
  if (!p.on && !p.marked) return "";
  const counts = Object.entries(p.counts).map(([k, v]) => `${v} ${k}`).join(", ");
  const parts = [counts || "nothing marked yet"];
  if (p.unlanded) parts.push(`${p.unlanded} unlanded past the window (counted against)`);
  if (p.on) parts.push(`graduates at ${Math.round(p.graduates_at.precision * 100)}% over ≥${p.graduates_at.min_marked} marked`);
  return parts.join(" · ");
}

export function stateColor(state: string): string {
  if (state === "live") return "var(--grn3)";
  if (state === "muted") return "var(--amb3)";
  return "var(--t3)";        // expired · disabled
}

export function ownerText(owner: { declared_by: string; agent_id: string }): string {
  return owner.declared_by || "—";
}
