"use client";

/**
 * ComposedCockpit — a cockpit drawn from a spec (Arc CT, CT-1 and CT-2; ROADMAP §3.50).
 *
 * The law of the arc: the spec arranges, the card store measures. This component draws tabs
 * and sections from the spec, and hands every card to `CockpitTile`, which draws the card's own
 * run at its metric's unit — nothing about what a card measures is decided in this file. (Until
 * the user's "make the cockpit look like the mockup", 2026-09-28, a card was drawn with the
 * Briefing's `PinnedCardBody` unchanged; the face changed, the law did not.)
 *
 * Three things it will not do:
 *   - draw a spec the rules refuse. It says why instead, in the rules' own sentences.
 *   - let a condition read anything the host did not publish. The state a cockpit renders
 *     against is the open tab plus the host's tree, laid over whatever the spec seeded.
 *   - hide a card without saying so. A section counts the cards waiting on a condition, a
 *     card the reader may not see stays where it is and says it is withheld, and a card
 *     that fails to draw says that too. The library wraps every element in an error
 *     boundary of its own that draws NOTHING when a component throws; the boundary here
 *     sits inside it, so the library's never gets the chance.
 *
 * The Briefing draws a person's cockpits with it (`BriefingCockpits`), behind `cockpit.composed`.
 */
import { Component, createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { evaluateVisibility, type Spec, type VisibilityCondition } from "@json-render/core";
import {
  JSONUIProvider, Renderer, createStateStore, useBoundProp, useStateStore,
  type ComponentRegistry, type ComponentRenderProps,
} from "@json-render/react";

import type { CardState } from "@/components/brief/PinnedCardBody";
import { CockpitTile, SaidTile, WIDE, WithheldTile, tileShape } from "@/components/cockpit/CockpitTile";
import { Icon } from "@/components/ui/icon";
import { Refusal } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { CockpitCard } from "@/lib/api";
import type { ComponentName, Tone } from "@/lib/cockpit/catalog";
import { stateModel, type CockpitHostState } from "@/lib/cockpit/hostState";
import { checkCockpitSpec, openingTab } from "@/lib/cockpit/rules";

export interface CockpitDoors {
  onRemove: (id: string) => void;
  onRefresh: (id: string) => void;
  onOpenSource?: (iid: string) => void;
  onEvidence?: (iid: string) => void;
}

interface CockpitContextValue {
  elements: Spec["elements"];
  cards: Map<string, CardState>;
  host: CockpitHostState;
  doors: CockpitDoors;
  sym: string;
}

const CockpitContext = createContext<CockpitContextValue | null>(null);

/** How many columns the section a card sits in draws — a wide tile takes two, where there are two. */
const SectionColumns = createContext(1);

function useCockpit(): CockpitContextValue {
  const ctx = useContext(CockpitContext);
  if (!ctx) throw new Error("a cockpit component was drawn outside ComposedCockpit");
  return ctx;
}

/** The rule down a card's left edge. A tone is emphasis; it never replaces the card's own frame. */
const TONE_RULE: Record<Tone, string> = {
  good: "var(--grn3)", warn: "var(--amb3)", bad: "var(--red3)", info: "var(--blue3)", neutral: "var(--b2)",
};

function CockpitRoot({ element, children }: ComponentRenderProps<{ title: string }>) {
  // The title names the cockpit for a screen reader and for the history. It is not drawn as a
  // header: the strip of cockpits above it already carries the name, and a panel does not
  // repeat its own title.
  return <div role="region" aria-label={element.props.title} data-testid="cockpit">{children}</div>;
}

function CockpitTabs({ element, children, bindings }: ComponentRenderProps<{ value: string }>) {
  const { elements } = useCockpit();
  const [open, setOpen] = useBoundProp<string>(element.props.value, bindings?.value);
  const tabs = (element.children ?? []).map(key => {
    const props = elements[key]?.props as { name: string; label: string };
    return { key, name: props.name, label: props.label };
  });
  return (
    <Tabs value={open ?? tabs[0]?.name} onValueChange={v => setOpen(String(v))}>
      <TabsList>
        {tabs.map(t => <TabsTrigger key={t.key} value={t.name}>{t.label}</TabsTrigger>)}
      </TabsList>
      {children}
    </Tabs>
  );
}

/** How many of an element's children a condition is hiding right now. */
function useWaiting(children: string[] | undefined): number {
  const { elements } = useCockpit();
  const { state } = useStateStore();
  return (children ?? []).filter(key => {
    const cond = elements[key]?.visible as VisibilityCondition | undefined;
    return cond !== undefined && !evaluateVisibility(cond, { stateModel: state });
  }).length;
}

function CockpitTab({ element, children }: ComponentRenderProps<{ name: string; label: string }>) {
  const waiting = useWaiting(element.children);
  return (
    <TabsContent value={element.props.name}>
      {children}
      {waiting > 0 && (
        <div className="aug-fs-sm" data-testid="cockpit-waiting-sections" style={{ color: "var(--t3)", marginTop: 16, display: "flex", alignItems: "center", gap: 6 }}>
          <Icon name="eyeoff" size={13} />
          {waiting === 1 ? "1 section waits on a condition" : `${waiting} sections wait on a condition`}
        </div>
      )}
    </TabsContent>
  );
}

/** The narrowest a tile is drawn. A section never asks for more columns than fit. */
const MIN_TILE = 200;
const GAP = 12;
const MAX_AUTO_COLUMNS = 4;

/** How many columns a section draws: the spec's, when it says, never more than fit. Width 0 is
 *  a section not yet measured (or a test's DOM), and draws as asked. */
function useColumns(asked: number | null | undefined): [RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  const fit = width > 0 ? Math.max(1, Math.floor((width + GAP) / (MIN_TILE + GAP))) : MAX_AUTO_COLUMNS;
  return [ref, Math.min(asked ?? MAX_AUTO_COLUMNS, fit)];
}

function CockpitSection({ element, children }: ComponentRenderProps<{ title: string; columns?: number | null }>) {
  const waiting = useWaiting(element.children);
  const [ref, columns] = useColumns(element.props.columns);
  return (
    <section data-testid="cockpit-section" style={{ marginTop: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, marginBottom: 10 }}>
        <div className="aug-fs-h2" style={{ fontWeight: 600, color: "var(--t1)" }}>{element.props.title}</div>
        {waiting > 0 && (
          <div className="aug-fs-sm" data-testid="cockpit-waiting" style={{ color: "var(--t3)", display: "flex", alignItems: "center", gap: 6 }}>
            <Icon name="eyeoff" size={13} />
            {waiting === 1 ? "1 card waits on a condition" : `${waiting} cards wait on a condition`}
          </div>
        )}
      </div>
      <div ref={ref} data-columns={columns} style={{
        display: "grid", gap: GAP, alignItems: "stretch", gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
      }}>
        <SectionColumns.Provider value={columns}>{children}</SectionColumns.Provider>
      </div>
    </section>
  );
}

/** A card that throws while drawing says so, in its own place. Keyed by the card, so a
 *  refresh that brings a run it CAN draw gets a fresh start. */
class CardBoundary extends Component<{ children: ReactNode }, { failed: string | null }> {
  state = { failed: null as string | null };

  static getDerivedStateFromError(error: unknown) {
    return { failed: error instanceof Error ? error.message : String(error) };
  }

  render() {
    if (this.state.failed === null) return this.props.children;
    return <SaidTile what="Could not be drawn">This card is here, and drawing it failed: {this.state.failed}</SaidTile>;
  }
}

function CockpitCard({ element }: ComponentRenderProps<{ card: string; tone?: Tone | null }>) {
  const { cards, host, doors, sym } = useCockpit();
  const columns = useContext(SectionColumns);
  const id = element.props.card;
  const tone = element.props.tone ?? null;
  const cs = cards.get(id);
  const status = host.cards[id]?.status ?? "unmeasured";
  const wide = !!cs && WIDE[tileShape(cs)];
  return (
    <div data-testid="cockpit-card" data-card={id} data-tone={tone ?? undefined} style={{
      position: "relative", borderRadius: "var(--r3)", minWidth: 0,
      gridColumn: wide ? `span ${Math.min(2, columns)}` : undefined,
      boxShadow: tone ? `inset 3px 0 0 ${TONE_RULE[tone]}` : undefined,
      paddingLeft: tone ? 3 : 0,
    }}>
      {status === "withheld"
        ? <WithheldTile />
        : !cs
          ? <SaidTile what="Not one of your cards">The cockpit places a card you do not have.</SaidTile>
          : (
            <CardBoundary key={`${id}:${cs.run ? JSON.stringify(cs.run.rows).length : 0}:${cs.failed ? 1 : 0}`}>
              <CockpitTile cs={cs as CardState & { card: CockpitCard }} status={status} sym={sym} doors={doors} />
            </CardBoundary>
          )}
    </div>
  );
}

/** One renderer per catalog component — a missing or an extra name is a type error. */
const REGISTRY = {
  Cockpit: CockpitRoot,
  Tabs: CockpitTabs,
  Tab: CockpitTab,
  Section: CockpitSection,
  Card: CockpitCard,
} satisfies Record<ComponentName, unknown>;

export function ComposedCockpit({ spec, cards, host, doors, sym = "$" }: {
  spec: unknown;
  cards: CardState[];
  host: CockpitHostState;
  doors: CockpitDoors;
  /** The symbol a money figure is written with (`currency_symbol` from the cockpit's read). */
  sym?: string;
}) {
  // A spec is known by what it says, not by which object says it: a caller that parses the
  // same JSON again on every render hands over a new object each time, and that must not
  // close the tab a reader opened.
  const written = useMemo(() => JSON.stringify(spec) ?? "", [spec]);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on what the spec says
  const check = useMemo(() => checkCockpitSpec(spec), [written]);

  // One store per spec. The host's tree is laid over it on every change, so a spec can seed
  // the open tab and nothing else, and a reader's choice of tab survives a refresh of the cards.
  const store = useMemo(
    () => createStateStore(stateModel(openingTab(spec), host)),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the host is laid over below, not at creation
    [written],
  );
  useEffect(() => {
    store.update({ "/range": { status: host.range.status }, "/cards": host.cards });
  }, [store, host]);

  const context = useMemo<CockpitContextValue>(() => ({
    elements: check.valid ? (spec as Spec).elements : {},
    cards: new Map(cards.map(c => [c.card.id, c])),
    host,
    doors,
    sym,
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on what the spec says
  }), [check.valid, written, cards, host, doors, sym]);

  if (!check.valid) {
    return (
      <Refusal
        kind="Refused · the cockpit's spec"
        claim="This cockpit is not drawn, because its spec breaks the rules a cockpit is held to."
        detail={
          <ul data-testid="cockpit-refusal" style={{ margin: 0, paddingLeft: 18 }}>
            {check.issues.map((issue, i) => <li key={`${issue.code}-${issue.elementKey ?? ""}-${i}`}>{issue.message}</li>)}
          </ul>
        }
      />
    );
  }

  return (
    <CockpitContext.Provider value={context}>
      <JSONUIProvider registry={REGISTRY as ComponentRegistry} store={store}>
        <Renderer spec={spec as Spec} registry={REGISTRY as ComponentRegistry} />
      </JSONUIProvider>
    </CockpitContext.Provider>
  );
}
