"use client";

/**
 * CockpitArrange — a cockpit's outline, arranged by hand (Arc CT, CT-8; ROADMAP §3.50).
 *
 * Tabs, their sections and the cards in each, as lines a person can move, rename and take off.
 * No card is drawn here and no query runs: arranging is about where things go, and a card's
 * figure is the card's own business, drawn on the cockpit itself.
 *
 * Every change goes through the pure edits in `lib/cockpit/edit.ts`, so what this screen holds
 * is always a spec, and the caller keeps it — as the next version of a cockpit, or, for a draft
 * not yet kept, as the person's changes to it.
 */
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  moveCardTo, moveCardToNewSection, moveSectionTo, moveSectionToNewTab, moveWithin, rename,
  sectionsOf, tabsOf, takeOff, type CockpitSpec,
} from "@/lib/cockpit/edit";

/** What a card is called on a line, and — for one a draft would create — what it will show. */
export interface CardLine { title: string; shows?: string; isNew?: boolean }

const NEW = "__new__";

function NameField({ label, value, onSave, testId }: {
  label: string; value: string; onSave: (v: string) => void; testId?: string;
}) {
  const [text, setText] = useState(value);
  const save = () => { if (text.trim() && text.trim() !== value) onSave(text); else setText(value); };
  return (
    <Input aria-label={label} data-testid={testId} value={text} onChange={e => setText(e.target.value)}
      onBlur={save} onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
      style={{ maxWidth: 320 }} />
  );
}

function Ask({ label, onDone }: { label: string; onDone: (name: string | null) => void }) {
  const [text, setText] = useState("");
  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
      <Input autoFocus aria-label={label} placeholder={label} value={text} onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter" && text.trim()) onDone(text); if (e.key === "Escape") onDone(null); }}
        style={{ width: 200 }} />
      <Button size="xs" disabled={!text.trim()} onClick={() => onDone(text)}>Add</Button>
      <Button size="xs" variant="ghost" onClick={() => onDone(null)}>Cancel</Button>
    </span>
  );
}

function MoveTo({ label, options, onPick }: {
  label: string; options: { v: string; t: string }[]; onPick: (v: string) => void;
}) {
  const items = Object.fromEntries(options.map(o => [o.v, o.t]));
  return (
    <Select value="" onValueChange={v => { if (v) onPick(String(v)); }} items={items}>
      <SelectTrigger size="sm" aria-label={label} style={{ minWidth: 120 }}>
        <SelectValue placeholder={label} />
      </SelectTrigger>
      <SelectContent>
        {options.map(o => <SelectItem key={o.v} value={o.v}>{o.t}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

export function CockpitArrange({ spec, lines, onChange, disabled }: {
  spec: CockpitSpec;
  /** Each card's line, by card id. */
  lines: Map<string, CardLine>;
  onChange: (next: CockpitSpec) => void;
  disabled?: boolean;
}) {
  const [asking, setAsking] = useState<{ kind: "section" | "tab"; key: string } | null>(null);
  const sections = sectionsOf(spec);
  const tabs = tabsOf(spec);
  const root = spec.elements[spec.root];

  const cardRow = (key: string, sectionKey: string, i: number, n: number) => {
    const el = spec.elements[key];
    const id = String(el.props.card ?? "");
    const line = lines.get(id);
    const elsewhere = sections.filter(s => s.key !== sectionKey).map(s => ({
      v: s.key, t: s.tabLabel ? `${s.tabLabel} · ${s.title}` : s.title,
    }));
    return (
      <li key={key} data-testid="arrange-card" data-card={id} style={{
        display: "flex", alignItems: "center", gap: 8, padding: "6px 0", borderBottom: "1px solid var(--b1)",
      }}>
        <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {line?.title || id}
          {line?.isNew && <Badge variant="outline" style={{ marginLeft: 8 }}>new</Badge>}
          {line?.shows && <span className="aug-fs-sm" style={{ color: "var(--t3)", marginLeft: 8 }}>{line.shows}</span>}
          {el.visible !== undefined && <span className="aug-fs-sm" style={{ color: "var(--t3)", marginLeft: 8 }}>· shown on a condition</span>}
        </span>
        {asking?.kind === "section" && asking.key === key ? (
          <Ask label="Name of the new section" onDone={name => {
            setAsking(null);
            if (name) onChange(moveCardToNewSection(spec, key, name));
          }} />
        ) : (
          <>
            <Button size="xs" variant="ghost" disabled={disabled || i === 0} aria-label="Move earlier"
              onClick={() => onChange(moveWithin(spec, key, -1))}>↑</Button>
            <Button size="xs" variant="ghost" disabled={disabled || i === n - 1} aria-label="Move later"
              onClick={() => onChange(moveWithin(spec, key, 1))}>↓</Button>
            <MoveTo label="Move to…" options={[...elsewhere, { v: NEW, t: "A new section…" }]}
              onPick={v => (v === NEW ? setAsking({ kind: "section", key }) : onChange(moveCardTo(spec, key, v)))} />
            <Button size="xs" variant="ghost" disabled={disabled} onClick={() => onChange(takeOff(spec, key))}>
              Take off
            </Button>
          </>
        )}
      </li>
    );
  };

  const sectionBlock = (key: string, i: number, n: number, tabKey: string | null) => {
    const el = spec.elements[key];
    const others = tabs.filter(t => t.key !== tabKey).map(t => ({ v: t.key, t: t.label }));
    return (
      <div key={key} data-testid="arrange-section" style={{ margin: "12px 0 18px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <NameField label="Section name" value={String(el.props.title ?? "")} testId="arrange-section-name"
            onSave={v => onChange(rename(spec, key, v))} />
          <Button size="xs" variant="ghost" disabled={disabled || i === 0} aria-label="Move section earlier"
            onClick={() => onChange(moveWithin(spec, key, -1))}>↑</Button>
          <Button size="xs" variant="ghost" disabled={disabled || i === n - 1} aria-label="Move section later"
            onClick={() => onChange(moveWithin(spec, key, 1))}>↓</Button>
          {asking?.kind === "tab" && asking.key === key ? (
            <Ask label="Name of the new tab" onDone={name => {
              setAsking(null);
              if (name) onChange(moveSectionToNewTab(spec, key, name));
            }} />
          ) : (
            <MoveTo label="Move to tab…" options={[...others, { v: NEW, t: "A new tab…" }]}
              onPick={v => (v === NEW ? setAsking({ kind: "tab", key }) : onChange(moveSectionTo(spec, key, v)))} />
          )}
          {el.visible !== undefined && <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>shown on a condition</span>}
        </div>
        <ul style={{ listStyle: "none", margin: "6px 0 0", padding: 0 }}>
          {el.children.map((c, j) => cardRow(c, key, j, el.children.length))}
        </ul>
      </div>
    );
  };

  const tabsKey = root.children.find(k => spec.elements[k]?.type === "Tabs");
  return (
    <div data-testid="cockpit-arrange">
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span className="aug-label">Cockpit</span>
        <NameField label="Cockpit name" value={String(root.props.title ?? "")} testId="arrange-cockpit-name"
          onSave={v => onChange(rename(spec, spec.root, v))} />
      </div>
      {tabsKey
        ? spec.elements[tabsKey].children.map((t, ti, all) => (
          <div key={t} data-testid="arrange-tab" style={{ borderTop: "1px solid var(--b1)", paddingTop: 10, marginTop: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="aug-label">Tab</span>
              <NameField label="Tab name" value={String(spec.elements[t].props.label ?? "")} testId="arrange-tab-name"
                onSave={v => onChange(rename(spec, t, v))} />
              <Button size="xs" variant="ghost" disabled={disabled || ti === 0} aria-label="Move tab earlier"
                onClick={() => onChange(moveWithin(spec, t, -1))}>↑</Button>
              <Button size="xs" variant="ghost" disabled={disabled || ti === all.length - 1} aria-label="Move tab later"
                onClick={() => onChange(moveWithin(spec, t, 1))}>↓</Button>
            </div>
            {spec.elements[t].children.map((s, i, list) => sectionBlock(s, i, list.length, t))}
          </div>
        ))
        : root.children.map((s, i, list) => sectionBlock(s, i, list.length, null))}
    </div>
  );
}
