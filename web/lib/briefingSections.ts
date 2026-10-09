/**
 * The Briefing's switches (the canvas, docs/COCKPIT_CANVAS_2026-10-08.md, B1).
 *
 * A person shows, hides and orders the Briefing's sections and chooses which cockpit of theirs
 * rides with it. The content of a section is never theirs to change, and a send carries the
 * platform's Briefing, not their switches. The preference is kept per person on the server
 * (`briefing_sections`, `aughor/db/user_prefs.py`), whose registry holds the same ids.
 *
 * Two of the switches are PARTS of the verdict block, not sections of their own (the user,
 * 2026-10-08, pointing at the tiles under the headline: "how do you use this functionality to
 * say that I do not wish to see the key metrics located inside the intelligence briefing?"):
 * the measured figures for the day, and the row of what the findings found. Each can be hidden
 * on its own; neither can be moved out of the verdict, so they move with it and have no order
 * of their own.
 *
 * A switch can be asked for in words. The words are read HERE, without a model: the vocabulary
 * is eight names, three verbs and a cockpit's name, and a model call to read "hide the findings"
 * would cost a person seconds for nothing. What the words come to is a proposal the person keeps
 * or not — words never write.
 */

export const BRIEFING_SECTIONS = [
  { id: "verdict", label: "Verdict — the headline" },
  { id: "measured", label: "Measured figures — the tiles under the headline", inside: "verdict" },
  { id: "moves", label: "What the findings found — the row under them", inside: "verdict" },
  { id: "key_metrics", label: "Key Metrics strip" },
  { id: "findings", label: "Findings" },
  { id: "synthesis", label: "Full synthesis" },
  { id: "cockpit", label: "Your cockpit" },
  { id: "patterns", label: "Top patterns" },
] as const;

export type SectionId = (typeof BRIEFING_SECTIONS)[number]["id"];
export interface SectionSwitch { id: SectionId; on: boolean }
export interface BriefingSectionsPref { sections: SectionSwitch[]; strip: string }

const IDS = BRIEFING_SECTIONS.map(s => s.id) as readonly SectionId[];
/** The parts of the verdict: hidden on their own, moved with it, never on their own. */
export const PARTS: readonly SectionId[] = BRIEFING_SECTIONS.filter(s => "inside" in s).map(s => s.id);

export function isPart(id: SectionId): boolean {
  return PARTS.includes(id);
}

export const DEFAULT_SECTIONS: BriefingSectionsPref = {
  sections: BRIEFING_SECTIONS.map(s => ({ id: s.id, on: true })),
  strip: "",
};

export function labelOf(id: SectionId): string {
  return BRIEFING_SECTIONS.find(s => s.id === id)?.label ?? id;
}

/** The parts put back directly after the verdict, in the registry's order: a part has no
 *  order of its own, wherever an older preference left it. */
function settled(sections: SectionSwitch[]): SectionSwitch[] {
  const parts = PARTS.map(id => sections.find(s => s.id === id)).filter((s): s is SectionSwitch => !!s);
  const rest = sections.filter(s => !isPart(s.id));
  const at = rest.findIndex(s => s.id === "verdict");
  return at < 0 ? [...rest, ...parts] : [...rest.slice(0, at + 1), ...parts, ...rest.slice(at + 1)];
}

/** The preference as stored, read as the page needs it: every section once, in the kept order,
 *  one the store never heard of dropped, one it left out appended and shown. */
export function normalizeSections(raw: unknown): BriefingSectionsPref {
  const r = (raw && typeof raw === "object" ? raw : {}) as { sections?: unknown; strip?: unknown };
  const seen = new Set<SectionId>();
  const sections: SectionSwitch[] = [];
  for (const item of Array.isArray(r.sections) ? r.sections : []) {
    const id = (item && typeof item === "object" ? (item as { id?: unknown }).id : null) as SectionId | null;
    if (!id || !IDS.includes(id) || seen.has(id)) continue;
    seen.add(id);
    sections.push({ id, on: (item as { on?: unknown }).on !== false });
  }
  for (const id of IDS) if (!seen.has(id)) sections.push({ id, on: true });
  return { sections: settled(sections), strip: typeof r.strip === "string" ? r.strip : "" };
}

export function toggled(pref: BriefingSectionsPref, id: SectionId, on: boolean): BriefingSectionsPref {
  return { ...pref, sections: pref.sections.map(s => (s.id === id ? { ...s, on } : s)) };
}

/** Move a section to `to` among the sections that have an order. The verdict takes its parts
 *  with it; a part does not move. */
export function moved(pref: BriefingSectionsPref, id: SectionId, to: number): BriefingSectionsPref {
  if (isPart(id)) return pref;
  const ordered = pref.sections.filter(s => !isPart(s.id));
  const it = ordered.find(s => s.id === id);
  if (!it) return pref;
  const rest = ordered.filter(s => s.id !== id);
  const at = Math.max(0, Math.min(rest.length, to));
  const next = [...rest.slice(0, at), it, ...rest.slice(at)];
  return { ...pref, sections: settled([...next, ...pref.sections.filter(s => isPart(s.id))]) };
}

// ── words ─────────────────────────────────────────────────────────────────────────────────────

/** What a section is called when a person asks for it. The first match wins, so "key metrics"
 *  is read before "metrics" would be, "what the findings found" before "findings", and "the
 *  tiles" are the measured figures under the headline. */
const WORDS: [RegExp, SectionId][] = [
  [/\bkey metrics?\b|\bmetrics? strip\b|\bindustry (?:kpis?|metrics?)\b/, "key_metrics"],
  [/\bwhat (?:the )?findings found\b|\bwhat moved\b|\bmovers?\b|\bmoves\b|\bfindings found\b/, "moves"],
  [/\bmeasured\b|\btiles?\b|\bfigures?\b|\bmetrics? (?:in|inside|under)\b|\bnumbers\b/, "measured"],
  [/\bmetrics\b/, "key_metrics"],
  [/\bverdict\b|\bhero\b|\bheadline\b|\blargest moves\b/, "verdict"],
  [/\bfindings?\b|\bledger\b/, "findings"],
  [/\bsynthesis\b|\bnarrative\b|\bfull text\b|\bprose\b/, "synthesis"],
  [/\bpatterns?\b/, "patterns"],
  [/\bcockpit\b|\bstrip\b|\bcards\b/, "cockpit"],
];

const HIDE = /^(hide|remove|drop|take off|take away|get rid of|collapse|turn off|close)\b|\bdon'?t (want|need|show|wish)\b|\bwithout\b|\bno longer\b|\bnot (?:wish|want) to see\b/;
const SHOW = /^(show|bring back|add|put back|turn on|open|unhide|restore)\b/;
const FIRST = /\b(first|top|up top|at the top|to the top|at the start|up front)\b/;
const LAST = /\b(last|bottom|at the end|to the end|at the bottom|to the bottom)\b/;
const BEFORE = /\b(before|above)\s+(?:the\s+)?(.+)$/;
const AFTER = /\b(after|below|under|beneath)\s+(?:the\s+)?(.+)$/;
const NO_STRIP = /\b(no|none|without|remove|hide)\b.*\b(cockpit|strip)\b|\b(cockpit|strip)\b.*\b(off|away|none)\b/;

export interface CockpitChoice { id: string; title: string }

export type SwitchProposal =
  | { kind: "proposal"; lines: string[]; next: BriefingSectionsPref }
  | { kind: "refused"; why: string };

function sectionIn(text: string): SectionId | null {
  for (const [re, id] of WORDS) if (re.test(text)) return id;
  return null;
}

/** The words, read as switches: hide or show a section, put one first, last, before or after
 *  another, and name the cockpit that rides with the Briefing. Several at once, separated by a
 *  comma, "and" or "then". */
export function proposeFromWords(words: string, pref: BriefingSectionsPref, cockpits: CockpitChoice[]): SwitchProposal {
  const lines: string[] = [];
  let next: BriefingSectionsPref = { ...pref, sections: pref.sections.map(s => ({ ...s })) };
  const clauses = words.toLowerCase().replace(/[.!?]+$/g, "").split(/\s*(?:,|;|\bthen\b|\band\b)\s*/).map(c => c.trim()).filter(Boolean);
  for (const clause of clauses) {
    // The cockpit that rides with the Briefing, by its name.
    const named = cockpits.find(c => c.title && clause.includes(c.title.toLowerCase()));
    if (named && /\b(strip|cockpit|ride|with|show|put|use)\b/.test(clause) && !HIDE.test(clause)) {
      next = { ...next, strip: named.id, sections: next.sections.map(s => (s.id === "cockpit" ? { ...s, on: true } : s)) };
      lines.push(`Let “${named.title}” ride with your Briefing`);
      continue;
    }
    if (NO_STRIP.test(clause) && !sectionIn(clause.replace(/\b(cockpit|strip)\b/g, ""))) {
      next = { ...next, strip: "" };
      lines.push("No cockpit rides with your Briefing");
      continue;
    }
    const id = sectionIn(clause);
    if (!id) continue;
    const label = labelOf(id);
    if (HIDE.test(clause)) {
      next = toggled(next, id, false);
      lines.push(isPart(id) ? `Hide “${label}” — the verdict's headline stays` : `Hide “${label}” — one line stays saying it is hidden`);
    } else if (isPart(id) && (FIRST.test(clause) || LAST.test(clause) || BEFORE.test(clause) || AFTER.test(clause))) {
      lines.push(`“${label}” is part of the verdict and moves with it; it can be shown or hidden`);
    } else if (FIRST.test(clause)) {
      next = moved(toggled(next, id, true), id, 0);
      lines.push(`Put “${label}” first`);
    } else if (LAST.test(clause)) {
      next = moved(toggled(next, id, true), id, next.sections.length);
      lines.push(`Put “${label}” last`);
    } else if (BEFORE.test(clause) || AFTER.test(clause)) {
      const m = (BEFORE.exec(clause) ?? AFTER.exec(clause)) as RegExpExecArray;
      const other = sectionIn(m[2]);
      if (!other || other === id || isPart(other)) { lines.push(`Where to put “${label}” was not read: name another section`); continue; }
      const after = /^(after|below|under|beneath)$/.test(m[1]);
      const without = next.sections.filter(s => s.id !== id && !isPart(s.id));
      const at = without.findIndex(s => s.id === other) + (after ? 1 : 0);
      next = moved(toggled(next, id, true), id, at);
      lines.push(`Put “${label}” ${after ? "after" : "before"} “${labelOf(other)}”`);
    } else if (SHOW.test(clause)) {
      next = toggled(next, id, true);
      lines.push(`Show “${label}”`);
    }
  }
  const acted = lines.filter(l => !l.startsWith("Where to put") && !l.includes("moves with it"));
  if (!acted.length) {
    return { kind: "refused", why: "Not read as a Briefing switch. You can hide or show a section — the verdict, its measured "
      + "figures, what the findings found, the key metrics strip, findings, synthesis, cockpit, patterns — put a section "
      + "first, last, before or after another, and name the cockpit that rides with the Briefing. The sections' content is the platform's." };
  }
  if (JSON.stringify(next) === JSON.stringify(pref)) {
    return { kind: "refused", why: `Your Briefing already reads that way: ${lines.join("; ").toLowerCase()}.` };
  }
  return { kind: "proposal", lines, next };
}
