"use client";

/**
 * Arc FA-2 — the door out of a piece: "Ask about these" for the objects ticked in a table or a list, "Ask about this set"
 * for the set a piece reads. A click — never a drag — keeps the subject in memory (`lib/askSubject.ts`) and opens the
 * Data Canvas on the dashboard's connection, where the question carries it. Offered only while
 * `canvas.ask_about_chosen` is on; off, a piece draws exactly what it drew.
 */
import { usePieces, type Picked, type SetQuery } from "@/components/dashboards/OntologyPieces";
import { Button } from "@/components/ui/button";
import { askAbout, dashboardOf, MAX_SUBJECT, nounOf } from "@/lib/askSubject";
import { conditionsFor } from "@/lib/dashboards/objectView";
import { useFlagOn } from "@/lib/flagOn";

export const ASK_FLAG = "canvas.ask_about_chosen";
const words = (id: string) => id.replace(/[_-]+/g, " ");

/** The control a piece's foot holds: the ticked objects while any are ticked, else the set it reads, by name — a set
 *  of its dashboard or a segment the ontology names — or nothing, for a piece over every object of an entity, which
 *  names no set to ask about. */
export function AskAboutPiece({ query, ticked, total, typeId }: {
  query: SetQuery; ticked: Picked[]; total: number | null | undefined; typeId: string;
}) {
  const on = useFlagOn(ASK_FLAG);
  const { connectionId, dashboardId, wire, valueOf, picked, filters } = usePieces();
  if (!on || !connectionId || !("entity" in query)) return null;
  const noun = nounOf(typeId);
  if (ticked.length) {
    const refs = ticked.slice(0, MAX_SUBJECT).map(p => `${p.objectType}:${p.pk}`);
    return (
      <Button size="xs" variant="ghost" data-testid="ask-about-ticked"
        onClick={() => askAbout({ kind: "objects", connectionId, noun, refs, ...(query.set ? { label: query.label || query.set } : {}) })}>
        Ask about these
      </Button>
    );
  }
  const mineOnly = conditionsFor(filters, query.entity);
  if (!query.set && query.segment) {
    // a segment the ontology names, read directly: the server reads its definition, under these conditions
    return (
      <Button size="xs" variant="ghost" data-testid="ask-about-set"
        onClick={() => askAbout({ kind: "segment", connectionId, noun, entity: query.entity, segment: query.segment,
          label: query.label || words(query.segment), total, filters: query.conditions as unknown as Record<string, unknown>[],
          narrowed: mineOnly.length > 0 })}>
        Ask about this set
      </Button>
    );
  }
  const where = query.set ? dashboardOf(dashboardId, connectionId) : null;
  if (!where) return null;
  // the values the set is read with on this page, and the objects chosen here — the server reads the set's own definition
  const values = Object.fromEntries(Object.keys(wire.values ?? {}).flatMap(n => {
    const now = valueOf(n);
    return "value" in now ? [[n, now.value]] : [];
  }));
  const chosen = Object.fromEntries(Object.entries(picked).map(([choice, p]) => [choice, p.pk]));
  const mine = mineOnly;
  return (
    <Button size="xs" variant="ghost" data-testid="ask-about-set"
      onClick={() => askAbout({ kind: "set", connectionId, noun, ...where, set: query.set, label: query.label || query.set,
        total, values, chosen, filters: mine, narrowed: mine.length > 0 })}>
      Ask about this set
    </Button>
  );
}
