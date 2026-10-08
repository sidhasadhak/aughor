/**
 * The Briefing's switches (the canvas, docs/COCKPIT_CANVAS_2026-10-08.md, B1).
 *
 * A person shows, hides and orders the Briefing's sections and chooses which cockpit of theirs
 * rides with it. The content of a section is never theirs to change, and a send carries the
 * platform's Briefing, not their switches. The preference is kept per person on the server
 * (`briefing_sections`, `aughor/db/user_prefs.py`), whose registry holds the same six ids.
 *
 * A switch can be asked for in words. The words are read HERE, without a model: the vocabulary
 * is six sections, three verbs and a cockpit's name, and a model call to read "hide the findings"
 * would cost a person seconds for nothing. What the words come to is a proposal the person keeps
 * or not — words never write.
 */

export const BRIEFING_SECTIONS = [
  { id: "verdict", label: "Verdict and largest moves" },
  { id: "key_metrics", label: "Key Metrics" },
  { id: "findings", label: "Findings" },
  { id: "synthesis", label: "Full synthesis" },
  { id: "cockpit", label: "Your cockpit" },
  { id: "patterns", label: "Top patterns" },
] as const;

export type SectionId = (typeof BRIEFING_SECTIONS)[number]["id"];
export interface SectionSwitch { id: SectionId; on: boolean }
export interface BriefingSectionsPref { sections: SectionSwitch[]; strip: string }

const IDS = BRIEFING_SECTIONS.map(s => s.id) as readonly SectionId[];

export const DEFAULT_SECTIONS: BriefingSectionsPref = {
  sections: BRIEFING_SECTIONS.map(s => ({ id: s.id, on: true })),
  strip: "",
};

export function labelOf(id: SectionId): string {
  return BRIEFING_SECTIONS.find(s => s.id === id)?.label ?? id;
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
  return { sections, strip: typeof r.strip === "string" ? r.strip : "" };
}

export function toggled(pref: BriefingSectionsPref, id: SectionId, on: boolean): BriefingSectionsPref {
  return { ...pref, sections: pref.sections.map(s => (s.id === id ? { ...s, on } : s)) };
}

export function moved(pref: BriefingSectionsPref, id: SectionId, to: number): BriefingSectionsPref {
  const rest = pref.sections.filter(s => s.id !== id);
  const it = pref.sections.find(s => s.id === id);
  if (!it) return pref;
  const at = Math.max(0, Math.min(rest.length, to));
  return { ...pref, sections: [...rest.slice(0, at), it, ...rest.slice(at)] };
}

// ── words ─────────────────────────────────────────────────────────────────────────────────────

/** What a section is called when a person asks for it. The first match wins, so "key metrics" is
 *  read before "metrics" would be, and "the findings" is the ledger, not the verdict's finding. */
const WORDS: [RegExp, SectionId][] = [
  [/\bkey metrics?\b|\bmetric tiles?\b|\btiles\b|\bmetrics\b/, "key_metrics"],
  [/\bverdict\b|\bhero\b|\blargest moves\b|\bmovers?\b/, "verdict"],
  [/\bfindings?\b|\bledger\b/, "findings"],
  [/\bsynthesis\b|\bnarrative\b|\bfull text\b|\bprose\b/, "synthesis"],
  [/\bpatterns?\b/, "patterns"],
  [/\bcockpit\b|\bstrip\b|\bcards\b/, "cockpit"],
];

const HIDE = /^(hide|remove|drop|take off|take away|get rid of|collapse|turn off|close)\b|\bdon'?t (want|need|show)\b|\bwithout\b/;
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
      lines.push(`Hide “${label}” — one line stays saying it is hidden`);
    } else if (FIRST.test(clause)) {
      next = moved(toggled(next, id, true), id, 0);
      lines.push(`Put “${label}” first`);
    } else if (LAST.test(clause)) {
      next = moved(toggled(next, id, true), id, next.sections.length);
      lines.push(`Put “${label}” last`);
    } else if (BEFORE.test(clause) || AFTER.test(clause)) {
      const m = (BEFORE.exec(clause) ?? AFTER.exec(clause)) as RegExpExecArray;
      const other = sectionIn(m[2]);
      if (!other || other === id) { lines.push(`Where to put “${label}” was not read: name another section`); continue; }
      const after = /^(after|below|under|beneath)$/.test(m[1]);
      const without = next.sections.filter(s => s.id !== id);
      const at = without.findIndex(s => s.id === other) + (after ? 1 : 0);
      next = moved(toggled(next, id, true), id, at);
      lines.push(`Put “${label}” ${after ? "after" : "before"} “${labelOf(other)}”`);
    } else if (SHOW.test(clause)) {
      next = toggled(next, id, true);
      lines.push(`Show “${label}”`);
    }
  }
  if (!lines.length || lines.every(l => l.startsWith("Where to put"))) {
    return { kind: "refused", why: "Not read as a Briefing switch. You can hide or show a section — verdict, key metrics, "
      + "findings, synthesis, cockpit, patterns — put one first, last, before or after another, and name the cockpit "
      + "that rides with the Briefing. The sections' content is the platform's." };
  }
  if (JSON.stringify(next) === JSON.stringify(pref)) {
    return { kind: "refused", why: `Your Briefing already reads that way: ${lines.join("; ").toLowerCase()}.` };
  }
  return { kind: "proposal", lines, next };
}
