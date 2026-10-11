/**
 * What one press of a cockpit's button runs (Arc AP-3; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.5).
 *
 * Each parameter of the declared action takes one source: the object a reader chose (it runs once), the objects they
 * ticked (once per object, each run its own, at most 50), every object of a set (asked first, said with its count, at
 * most 50), what the form asks, or the same value every time. A parameter the button wires to nothing is asked when it
 * is a value, and stops the button — saying why — when it is an object: a cockpit never guesses which object an action
 * runs on.
 *
 * Planning is pure, here; running is the piece's (`ActionButtonsPiece`), one call to the declared action's own door per
 * object, so the declaration's criteria, risk and approval hold on every run — a high-risk action on twenty ticked
 * orders is twenty proposals, never one silent batch.
 */
import { MAX_TICKED_RUNS, type ActionButtonDef } from "@/lib/cockpit/catalog";

export interface ParamDecl {
  name: string;
  display_name: string;
  data_type: string;
  required: boolean;
  default_value: string | null;
  kind: "value" | "object";
  object_type: string;
  description: string;
}

export interface ChosenObject { pk: string; typeId: string; objectType: string }

export interface RunContext {
  kindOf: (choice: string) => "chosen" | "ticked" | "shown" | undefined;
  chosen: (choice: string) => ChosenObject | null;
  ticked: (choice: string) => ChosenObject[];
}

export type RunPlan =
  | { blocked: string }
  | {
    /** Values every run takes: a chosen object's key, a fixed value. */
    fixed: Record<string, unknown>;
    /** The one parameter run once per object, with the objects' keys — ticked ones now, a set's at the press. */
    each: { param: string; pks: string[] } | null;
    set: { param: string; set: string } | null;
    /** The value parameters the form asks, needed ones first. */
    asks: ParamDecl[];
    /** What each object parameter is filled with, as the form says it. */
    said: { param: ParamDecl; words: string }[];
  };

const words = (s: string) => s.replace(/[_-]+/g, " ").trim();
const named = (p: ParamDecl) => p.display_name || words(p.name);
const an = (w: string) => (/^[aeiou]/i.test(w) ? `an ${w}` : `a ${w}`);

/** What a press of `button` runs, given the declared action's parameters and what the reader has chosen and ticked. */
export function planRuns(button: ActionButtonDef, params: ParamDecl[], ctx: RunContext): RunPlan {
  const fixed: Record<string, unknown> = {};
  const asks: ParamDecl[] = [];
  const said: { param: ParamDecl; words: string }[] = [];
  let each: { param: string; pks: string[] } | null = null;
  let set: { param: string; set: string } | null = null;
  for (const p of params) {
    const src = button.params?.[p.name];
    const thing = words(p.object_type || p.name).toLowerCase();
    if (!src) {
      if (p.kind === "object") return { blocked: `${named(p)} is wired to no chosen object, ticked objects or set.` };
      asks.push(p);
      continue;
    }
    if ("ask" in src) { asks.push(p); continue; }
    if ("value" in src) { fixed[p.name] = src.value; continue; }
    if ("set" in src) {
      if (each || set) return { blocked: "Two parameters run once per object; one may." };
      set = { param: p.name, set: src.set };
      said.push({ param: p, words: `every ${thing} in ${words(src.set)}` });
      continue;
    }
    const kind = ctx.kindOf(src.from);
    if (kind === "chosen") {
      const o = ctx.chosen(src.from);
      if (!o) return { blocked: `Choose ${an(thing)} first.` };
      fixed[p.name] = o.pk;
      said.push({ param: p, words: `${words(o.typeId)} ${o.pk}` });
    } else if (kind === "ticked") {
      const list = ctx.ticked(src.from);
      if (!list.length) return { blocked: `Tick at least one ${thing}.` };
      if (list.length > MAX_TICKED_RUNS) return { blocked: `${list.length} are ticked; a press runs on at most ${MAX_TICKED_RUNS}.` };
      if (each || set) return { blocked: "Two parameters run once per object; one may." };
      each = { param: p.name, pks: list.map(o => o.pk) };
      said.push({ param: p, words: `${list.length} ticked ${list.length === 1 ? thing : `${thing}s`}` });
    } else {
      return { blocked: `${named(p)} comes from ${words(src.from)}, which no table chooses or ticks.` };
    }
  }
  // needed questions first, so the form reads as what must be said, then what may be
  asks.sort((a, b) => Number(!(a.required && a.default_value == null)) - Number(!(b.required && b.default_value == null)));
  return { fixed, each, set, asks, said };
}

/** The params of every run a plan makes: the fixed ones, what the form was told, and — for the parameter run per
 *  object — each object's key in turn. */
export function runsOf(plan: Exclude<RunPlan, { blocked: string }>, asked: Record<string, unknown>, setKeys: string[] = []): Record<string, unknown>[] {
  const base = { ...plan.fixed, ...Object.fromEntries(Object.entries(asked).filter(([, v]) => v !== "" && v !== undefined && v !== null)) };
  const per = plan.each ?? (plan.set ? { param: plan.set.param, pks: setKeys } : null);
  return per ? per.pks.map(pk => ({ ...base, [per.param]: pk })) : [base];
}

export type PressOutcome = { status: "ran" } | { status: "proposed" } | { status: "refused"; message: string }
  | { status: "failed"; message: string };

/** What a press did, in a sentence: how many ran, how many wait for approval, how many the action refused and why — and
 *  how many failed, said as failures: a server that broke is never a refusal the action made. */
export function pressSaid(outcomes: PressOutcome[], thing: string): string {
  const ran = outcomes.filter(o => o.status === "ran").length;
  const proposed = outcomes.filter(o => o.status === "proposed").length;
  const refused = outcomes.filter((o): o is { status: "refused"; message: string } => o.status === "refused");
  const failed = outcomes.filter((o): o is { status: "failed"; message: string } => o.status === "failed");
  const n = (k: number) => (k === 1 ? `1 ${thing}` : `${k} ${thing}s`);
  const one = outcomes.length === 1;
  const parts = [
    ran ? (one ? "Done." : `Ran on ${n(ran)}.`) : "",
    proposed ? (one ? "It needs approval — proposed in Actions." : `${proposed} wait for approval in Actions.`) : "",
    refused.length ? (one ? refused[0].message : `${refused.length} refused: ${refused[0].message}`) : "",
    failed.length ? (one ? `It did not run: ${failed[0].message}` : `${failed.length} did not run: ${failed[0].message}`) : "",
  ];
  // each part its own sentence, so two read as two: "1 refused: … closed. 1 did not run: …"
  return parts.filter(Boolean).map(x => (/[.!?]$/.test(x) ? x : `${x}.`)).join(" ");
}
