"use client";

/**
 * ComposedCockpit — a cockpit drawn from a spec (Arc CT, CT-1 and CT-2; ROADMAP §3.50).
 *
 * The law of the arc: the spec arranges, the card store measures. This component draws tabs
 * and sections from the spec, and hands every card to `PinnedCardBody` UNCHANGED — the same
 * component the Briefing's cockpit draws with — so a chart here is the same Vega chart it is
 * there, and nothing about what a card measures is decided in this file.
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
 * Nothing mounts this yet. CT-4 puts it in the Data Canvas behind `cockpit.composed`.
 */
import { Component, createContext, useContext, useEffect, useMemo, type ReactNode } from "react";
import { evaluateVisibility, type Spec, type VisibilityCondition } from "@json-render/core";
import {
  JSONUIProvider, Renderer, createStateStore, useBoundProp, useStateStore,
  type ComponentRegistry, type ComponentRenderProps,
} from "@json-render/react";

import { PinnedCardBody, type CardState } from "@/components/brief/PinnedCardBody";
import { CARD_H } from "@/components/brief/PinnedCardsGrid";
import { Refusal } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
}

const CockpitContext = createContext<CockpitContextValue | null>(null);

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
  // header: the canvas already carries the name, and a panel does not repeat its own title.
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
      <TabsList variant="line">
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
        <div className="aug-fs-sm" data-testid="cockpit-waiting-sections" style={{ color: "var(--t3)", marginTop: 16 }}>
          {waiting === 1 ? "1 section waits on a condition" : `${waiting} sections wait on a condition`}
        </div>
      )}
    </TabsContent>
  );
}

function CockpitSection({ element, children }: ComponentRenderProps<{ title: string; columns?: number | null }>) {
  const waiting = useWaiting(element.children);
  const columns = element.props.columns;
  return (
    <section data-testid="cockpit-section" style={{ marginTop: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, marginBottom: 8 }}>
        <div className="aug-label">{element.props.title}</div>
        {waiting > 0 && (
          <div className="aug-fs-sm" data-testid="cockpit-waiting" style={{ color: "var(--t3)" }}>
            {waiting === 1 ? "1 card waits on a condition" : `${waiting} cards wait on a condition`}
          </div>
        )}
      </div>
      <div style={{
        display: "grid", gap: 12, alignItems: "start",
        gridTemplateColumns: columns
          ? `repeat(${columns}, minmax(0, 1fr))`
          : "repeat(auto-fill, minmax(280px, 1fr))",
      }}>
        {children}
      </div>
    </section>
  );
}

function Said({ what, children }: { what: string; children: ReactNode }) {
  return (
    <div className="aug-fs-sm" data-testid="cockpit-card-said" style={{
      height: "100%", boxSizing: "border-box", padding: "9px 12px",
      border: "1px dashed var(--b2)", borderRadius: "var(--r3)", color: "var(--t2)",
    }}>
      <div style={{ fontWeight: 500, color: "var(--t1)" }}>{what}</div>
      <div style={{ marginTop: 4 }}>{children}</div>
    </div>
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
    return <Said what="Could not be drawn">This card is here, and drawing it failed: {this.state.failed}</Said>;
  }
}

function CockpitCard({ element }: ComponentRenderProps<{ card: string; tone?: Tone | null }>) {
  const { cards, host, doors } = useCockpit();
  const id = element.props.card;
  const tone = element.props.tone ?? null;
  const cs = cards.get(id);
  const withheld = host.cards[id]?.status === "withheld";
  return (
    <div data-testid="cockpit-card" data-card={id} data-tone={tone ?? undefined} style={{
      height: CARD_H, position: "relative", borderRadius: "var(--r3)",
      boxShadow: tone ? `inset 3px 0 0 ${TONE_RULE[tone]}` : undefined,
      paddingLeft: tone ? 3 : 0,
    }}>
      {withheld
        ? <Said what="Withheld">You may not see this card. It is here, and it is not empty.</Said>
        : !cs
          ? <Said what="Not in this canvas">The cockpit places a card this canvas does not hold.</Said>
          : (
            <CardBoundary key={`${id}:${cs.run ? JSON.stringify(cs.run.rows).length : 0}:${cs.failed ? 1 : 0}`}>
              <PinnedCardBody cs={cs} onRemove={doors.onRemove} onRefresh={doors.onRefresh}
                onOpenSource={doors.onOpenSource} onEvidence={doors.onEvidence} />
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

export function ComposedCockpit({ spec, cards, host, doors }: {
  spec: unknown;
  cards: CardState[];
  host: CockpitHostState;
  doors: CockpitDoors;
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on what the spec says
  }), [check.valid, written, cards, host, doors]);

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
