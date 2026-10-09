"use client";

/**
 * PinStrip — the ontology release a cockpit holding pieces was composed against, said above it (Arc OC-4; the study's
 * §8.7: a cockpit is checked against the release it is pinned to).
 *
 * The pieces always read what is published now. What a reader is owed is whether that is still what the cockpit was
 * built on: when a release since has changed something a piece reads — a process's promise, a rule, an action — the
 * strip names it, with the class it was published as, and the person who keeps the cockpit re-pins it once they have
 * looked. A cockpit with no piece draws no strip.
 */
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { CLASS_LOOK } from "@/components/ontology/ReleaseStrip";
import type { CockpitPin } from "@/lib/api";
import { withUniqueKeys } from "@/lib/listKeys";

const PIECE_WORDS: Record<string, string> = {
  ProcessBoard: "process board", ObjectTable: "objects table", ObjectDetail: "object detail", ActionButton: "action button",
};

const numberOf = (id: string) => id.slice(id.lastIndexOf("@") + 1);

export function PinStrip({ pin, spec, busy, onRepin }: {
  pin: CockpitPin;
  spec: unknown;
  busy?: boolean;
  /** Absent on a cockpit the reader may not change. */
  onRepin?: () => void;
}) {
  const elements = ((spec as { elements?: Record<string, { type?: string }> })?.elements) ?? {};
  const pieceWords = (keys: string[]) => [...new Set(keys.map(k => PIECE_WORDS[elements[k]?.type ?? ""] ?? k))].join(", ");
  const now = pin.current ? `release ${numberOf(pin.current)}` : "no release";
  const repin = onRepin && pin.current && (
    <Button size="xs" variant={pin.changes.length ? "secondary" : "ghost"} disabled={busy} data-testid="cockpit-repin"
      title={`Keep this cockpit as it is, composed against ${now}`} onClick={onRepin}>
      {pin.pinned ? `Re-pin to ${now}` : `Pin to ${now}`}
    </Button>
  );
  if (pin.pinned && pin.pinned === pin.current) {
    return (
      <div className="aug-fs-xs" data-testid="cockpit-pin" style={{ color: "var(--t3)", margin: "2px 0 6px", display: "flex", alignItems: "center", gap: 6 }}>
        <Icon name="layers" size={12} /> Its pieces read {now} of the ontology, the one it was composed against.
      </div>
    );
  }
  return (
    <div data-testid="cockpit-pin" className="aug-fs-sm"
      style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "8px 12px", margin: "4px 0 10px", display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", color: "var(--t2)" }}>
        <Icon name="layers" size={13} />
        <span>
          {pin.pinned
            ? <>Composed against release {numberOf(pin.pinned)}; its pieces read {now}.{" "}
                {pin.changes.length ? `${pin.changes.length === 1 ? "One change" : `${pin.changes.length} changes`} since touch what they read:`
                  : "Nothing they read has changed since."}</>
            : <>Not pinned to a release; its pieces read {now}.</>}
        </span>
        <span style={{ marginLeft: "auto" }}>{repin}</span>
      </div>
      {pin.changes.length > 0 && (
        <ul style={{ margin: 0, padding: 0 }}>
          {withUniqueKeys(pin.changes, c => `${c.release}/${c.kind}/${c.target_id}`).map(([k, c]) => (
            <li key={k} data-testid="cockpit-pin-change" className="aug-fs-xs" style={{ listStyle: "none", display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", color: "var(--t2)" }}>
              <span className={`aug-tag ${CLASS_LOOK[c.class].tag}`}>{CLASS_LOOK[c.class].label}</span>
              <span>
                {c.kind} <span style={{ fontFamily: "var(--font-mono)" }}>{c.target_id}</span> {c.change} in release {c.number}
                {" "}· read by the {pieceWords(c.pieces)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
