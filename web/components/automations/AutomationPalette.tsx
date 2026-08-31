"use client";

/**
 * DS-1 · the palette — the canvas's vocabulary, on the canvas.
 *
 * Before this, adding a step meant clicking "Add Action", getting a `notify` row you did
 * not ask for, and changing its kind afterwards from a `<select>` that showed nine words
 * and explained none of them. The descriptions for those kinds had been written months
 * earlier and rendered nowhere. This panel is where they finally are.
 *
 * **It refuses to look the same on every deployment.** Each row carries the server's
 * reading of whether the object that kind REFERENCES exists here (`/automations/palette`),
 * so an install with no Slack bot sees "Post to Slack" dimmed with the sentence that says
 * why, instead of discovering it at save. That is §3.4's alt-door rule — a card offers the
 * door this deployment can open — applied one level down, to every entry.
 *
 * **Two add paths, one gate.** A row can be clicked (or Entered) and it appends; it can be
 * dragged and it lands where it was dropped. Both call the single `onAdd` the canvas owns,
 * because an affordance that adds by a path the gate does not know about is how a refusal
 * comes to disagree with itself. The placement arithmetic lives in `automationFlow.ts` —
 * jsdom cannot see geometry, so the part that is silently wrong by a viewport is pure.
 *
 * Search is a plain normalised substring over label · description · kind, not a fuzzy
 * index: the population is nine entries, and on nine items fuzziness returns noise a
 * reader has to discard rather than the near-miss tolerance it buys over hundreds
 * (`CommandPalette` has the Fuse index, and hundreds of rows to justify it).
 */
import React from "react";

import { Button } from "@/components/ui/button";
import { Icon, type IconName } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { getAutomationPalette, type AutomationPaletteEntry } from "@/lib/api";

export type PaletteGroup = "trigger" | "action";

const GROUP_TITLE: Record<PaletteGroup, string> = {
  trigger: "Triggers",
  action: "Actions",
};

/** The panel is a fixed column beside the canvas; 232 keeps a two-word label and its
 *  badge on one line at 13px without the row wrapping, measured against the longest
 *  label the server offers ("Deliver briefing"). */
const PALETTE_W = 232;

function norm(s: string): string {
  return s.toLowerCase().normalize("NFKD");
}

function matches(entry: AutomationPaletteEntry, query: string): boolean {
  if (!query) return true;
  const q = norm(query);
  return norm(`${entry.label} ${entry.description} ${entry.kind}`).includes(q);
}

/** The server's curated order first, then alphabetical — the same three-key idea the
 *  reference palette uses, minus the search score a substring match does not produce. */
function ordered(entries: AutomationPaletteEntry[]): AutomationPaletteEntry[] {
  return [...entries].sort((a, b) =>
    a.priority !== b.priority ? a.priority - b.priority : a.label.localeCompare(b.label));
}

/** What a row hands to the canvas on a drag, and the smallest thing the add gate needs.
 *
 *  Deliberately not the whole entry: a payload carrying labels and availability would be
 *  a second copy of the server's answer, decided at drag time and acted on at drop time.
 *  The kind and its group are the only two facts placement turns on. */
export const PALETTE_DRAG_TYPE = "application/x-aughor-palette";

export interface PalettePlacement { kind: string; group: PaletteGroup }

/** Read a drop back, tolerating anything that is not ours. */
export function readPaletteDrag(data: string | null | undefined): PalettePlacement | null {
  if (!data) return null;
  try {
    const parsed = JSON.parse(data) as Partial<PalettePlacement>;
    if (!parsed?.kind || (parsed.group !== "trigger" && parsed.group !== "action")) return null;
    return { kind: parsed.kind, group: parsed.group };
  } catch {
    return null;
  }
}

interface RowProps {
  entry: AutomationPaletteEntry;
  onAdd: (placement: PalettePlacement) => void;
}

function PaletteRow({ entry, onAdd }: RowProps) {
  const usable = entry.availability === "ready";
  const gives = entry.publishes === null ? "its outcome" : entry.publishes.join(", ");

  return (
    <div
      draggable={usable}
      onDragStart={(e) => {
        e.dataTransfer.setData(PALETTE_DRAG_TYPE,
          JSON.stringify({ kind: entry.kind, group: entry.group }));
        e.dataTransfer.effectAllowed = "copy";
      }}
      style={{
        display: "flex", alignItems: "center", gap: 7,
        padding: "5px 6px", marginBottom: 3,
        borderRadius: "var(--r2)",
        border: "1px solid var(--b1)",
        background: usable ? "var(--bg-2)" : "var(--bg-1)",
        opacity: usable ? 1 : 0.62,
        cursor: usable ? "grab" : "not-allowed",
      }}
      data-testid={`palette-row-${entry.kind}`}
    >
      <Icon name={entry.icon as IconName} size={14} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          className="aug-fs-sm"
          style={{
            color: "var(--t1)", fontWeight: 500,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}
          title={entry.description}
        >
          {entry.label}
        </div>
        {/* The ports, in words. A reader deciding between two steps is usually deciding
            what the next one can bind to, and that is not visible until the node is on
            the canvas otherwise. */}
        {!!gives && usable && (
          <div className="aug-fs-xs" style={{ color: "var(--t4)" }}>
            gives {gives}
          </div>
        )}
      </div>
      {usable && (
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label={`Add ${entry.label} to the canvas`}
          onClick={() => onAdd({ kind: entry.kind, group: entry.group })}
        >
          <Icon name="plus" size={12} />
        </Button>
      )}
    </div>
  );
}

export interface AutomationPaletteProps {
  /** The automation's connection — scopes the objects that are themselves
   *  connection-scoped (subscriptions, monitors) when the server counts them. */
  connId?: string;
  /** Show only this group. The on-canvas "Add Trigger" / "Add Action" buttons open the
   *  palette already narrowed, which is what those buttons always meant. */
  only?: PaletteGroup;
  /** The ONE add gate — click and drop both arrive here (drop with a position). */
  onAdd: (placement: PalettePlacement, position?: { x: number; y: number }) => void;
  onClose: () => void;
}

export function AutomationPalette({ connId, only, onAdd, onClose }: AutomationPaletteProps) {
  const [entries, setEntries] = React.useState<AutomationPaletteEntry[] | null>(null);
  const [failed, setFailed] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const searchRef = React.useRef<HTMLInputElement>(null);

  // Not cached module-side, unlike the vocabulary: this document counts objects that a
  // reader can create in another tab, and a palette insisting you have no bots an hour
  // after you made one is worse than one request per open.
  React.useEffect(() => {
    let live = true;
    getAutomationPalette(connId)
      .then(rows => { if (live) { setEntries(rows); setFailed(false); } })
      .catch(() => { if (live) { setEntries([]); setFailed(true); } });
    return () => { live = false; };
  }, [connId]);

  React.useEffect(() => { searchRef.current?.focus(); }, []);

  // Switching halves clears the query. The panel stays mounted while the canvas's two
  // buttons swap `only` between them, so a search typed against Actions would otherwise
  // survive into Triggers and silently hide everything in it.
  React.useEffect(() => { setQuery(""); }, [only]);

  const groups: PaletteGroup[] = only ? [only] : ["trigger", "action"];
  // Scoped to the half being SHOWN before the search is applied — found by driving it:
  // computing the empty state over every entry meant a query matching only the other
  // half ("channel", with Triggers open) rendered no rows, no heading and no message,
  // which reads as a broken panel rather than an empty result.
  const inScope = (entries ?? []).filter(e => !only || e.group === only);
  const shown = inScope.filter(e => matches(e, query));

  return (
    <div
      style={{
        width: PALETTE_W, flexShrink: 0, display: "flex", flexDirection: "column",
        border: "1px solid var(--border)", borderRadius: 8,
        background: "var(--bg-1)", overflow: "hidden",
      }}
      data-testid="automation-palette"
    >
      <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "6px 6px 4px" }}>
        <Input
          ref={searchRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
          placeholder="Search steps…"
          aria-label="Search the palette"
          className="aug-fs-sm"
          style={{ height: 26 }}
        />
        <Button variant="ghost" size="icon-xs" aria-label="Close the palette" onClick={onClose}>
          <Icon name="close" size={12} />
        </Button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "0 6px 6px" }}>
        {entries === null ? (
          <div className="aug-fs-xs" style={{ color: "var(--t4)", padding: "6px 4px" }}>
            Loading…
          </div>
        ) : failed ? (
          // A palette that could not load must not read as a platform with nothing in it.
          <div className="aug-fs-xs" style={{ color: "var(--t3)", padding: "6px 4px" }}>
            Could not load the palette — the canvas still adds steps from the buttons above.
          </div>
        ) : (
          groups.map((group) => {
            const rows = ordered(shown.filter(e => e.group === group));
            if (!rows.length) return null;
            return (
              <div key={group} style={{ marginTop: 4 }}>
                <div
                  className="aug-fs-xs"
                  style={{
                    color: "var(--t4)", textTransform: "uppercase",
                    letterSpacing: "0.06em", padding: "4px 4px 5px",
                  }}
                >
                  {GROUP_TITLE[group]}
                </div>
                {rows.map(entry => (
                  <React.Fragment key={entry.kind}>
                    <PaletteRow entry={entry} onAdd={onAdd} />
                    {entry.availability !== "ready" && (
                      // The reason sits UNDER its row rather than in a tooltip: it is the
                      // one thing a reader needs in order to act, and a hover is not a
                      // place to put an instruction.
                      <div
                        className="aug-fs-xs"
                        style={{ color: "var(--t3)", padding: "0 6px 6px", lineHeight: 1.45 }}
                        data-testid={`palette-reason-${entry.kind}`}
                      >
                        {entry.reason}
                      </div>
                    )}
                  </React.Fragment>
                ))}
              </div>
            );
          })
        )}
        {entries !== null && !failed && !shown.length && (
          <div className="aug-fs-xs" style={{ color: "var(--t4)", padding: "6px 4px" }}>
            Nothing matches “{query}”.
          </div>
        )}
      </div>
    </div>
  );
}

export default AutomationPalette;
