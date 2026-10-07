"use client";

/**
 * Filed and open, and what is on probation — two sections of Agent Ops ▸ By duty (ROADMAP §6
 * item 42d; the hub's HB-3 doors, which had no screen).
 *
 * A filing is a ticket, a thread, a webhook or a document filed against a thing the platform
 * knows — a promise, a process, a finding, an entity — by an automation's send or by a person.
 * This lists every open one, whatever it is about, and closes one with what happened: the
 * outcome is what turns a push into a result somebody can count. Probation already has two
 * screens (the Hub map's column, and Departures); here it is one count and the door to them.
 */
import { useState } from "react";

import { Absent, ActorField, Gate, Ledger, Section, day, useActor, useLoad, type LedgerColumn } from "@/components/record/kit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";
import { closeFiling, getHubMap, listFilings, type Filing } from "@/lib/api";
import { countNoun } from "@/lib/format";
import { keyToWords } from "@/lib/names";
import { whoLabel } from "@/lib/record";

const KIND_WORD: Record<Filing["kind"], string> = {
  ticket: "Ticket", thread: "Thread", webhook: "Webhook", doc: "Document",
};

/** What a filing is called in a sentence: its title, else its reference, else its kind. */
export function filingName(f: Filing): string {
  return f.title || f.ref || KIND_WORD[f.kind] || f.kind;
}

/** `promise:order_to_delivery.dispatch` read as "promise · order to delivery.dispatch". */
export function aboutWords(ref: string): string {
  const [kind, ...rest] = ref.split(":");
  const key = rest.join(":");
  return key ? `${keyToWords(kind)} · ${keyToWords(key)}` : ref;
}

/** Whole days a filing has been open. */
export function openFor(ts: string, now = Date.now()): string {
  const then = Date.parse(ts);
  if (Number.isNaN(then)) return "";
  const days = Math.max(0, Math.floor((now - then) / 86_400_000));
  return days === 0 ? "today" : countNoun(days, "day");
}

export function FilingsSection() {
  const filings = useLoad(() => listFilings("open"), []);
  const actor = useActor();
  const [closing, setClosing] = useState<Filing | null>(null);
  const [outcome, setOutcome] = useState("");
  const [recovered, setRecovered] = useState("");
  const [busy, setBusy] = useState(false);

  const start = (f: Filing) => { setClosing(f); setOutcome(""); setRecovered(""); };
  const submit = async () => {
    if (!closing || !outcome.trim()) return;
    setBusy(true);
    try {
      await closeFiling(closing.id, outcome.trim(), recovered.trim());
      toast.success(`Closed “${filingName(closing)}”.`);
      setClosing(null);
      filings.reload();
    } catch (e) {
      toast.error("It was not closed", { description: (e as Error).message.slice(0, 160) });
    } finally { setBusy(false); }
  };

  const columns: LedgerColumn<Filing>[] = [
    { head: "Filed", cell: f => filingName(f) },
    { head: "Kind", cell: f => KIND_WORD[f.kind] ?? f.kind, width: 100 },
    {
      head: "Reference", width: 170,
      cell: f => (f.url
        ? <Button variant="link" size="xs" title={f.url} onClick={() => window.open(f.url, "_blank", "noopener")}>{f.ref || "Open it"}</Button>
        : f.ref || "—"),
    },
    { head: "About", cell: f => aboutWords(f.object_ref), width: 280 },
    { head: "Filed on", cell: f => day(f.ts), width: 110 },
    { head: "Open for", cell: f => openFor(f.ts), width: 100 },
    // `user:` with no name is what the door writes when nobody is signed in.
    { head: "By", cell: f => (f.source === "user:" ? "a person, not signed in" : whoLabel(f.source)), width: 190 },
    {
      head: "Close", control: true, width: 90,
      cell: f => <Button size="xs" variant="ghost" disabled={busy} onClick={() => start(f)}>Close</Button>,
    },
  ];

  return (
    <Section label="Filed and open" meta={filings.data ? countNoun(filings.data.length, "filing") : undefined}>
      <Gate load={filings} what="the open filings">
        {rows => (
          <>
            <Ledger name="open-filings" columns={columns} rows={rows} rowKey={f => f.id} selected={closing?.id}
              empty="Nothing is filed and open. A ticket, a thread or a document filed against a promise, a process or a finding is listed here until it is closed with what happened." />
            {closing && (
              <div className="aug-item" data-testid="filing-close">
                <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>Close “{filingName(closing)}” — what happened?</div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 8 }}>
                  <Input aria-label="What happened" placeholder="what happened, in a sentence" value={outcome}
                    onChange={e => setOutcome(e.target.value)} style={{ flex: "1 1 320px" }} />
                  <Input aria-label="What it recovered" placeholder="what it recovered, if anything — e.g. 34 late lines" value={recovered}
                    onChange={e => setRecovered(e.target.value)} style={{ flex: "0 1 320px" }} />
                  <ActorField actor={actor} id="filing-closer" />
                  <Button size="sm" disabled={busy || !outcome.trim()} onClick={() => void submit()}>Close it</Button>
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => setClosing(null)}>Cancel</Button>
                </div>
                <div className="aug-item-foot aug-fs-sm">
                  <span>Closing says what happened. For a promise, its measures are read again now and kept beside the ones read when it was filed.</span>
                </div>
              </div>
            )}
          </>
        )}
      </Gate>
    </Section>
  );
}

export function ProbationSection({ onOpenHub }: { onOpenHub: () => void }) {
  // A missing door is an answer, not a wait: `absent` says the hub map is not on this install.
  const hub = useLoad(async () => (await getHubMap()) ?? { absent: true as const }, []);
  return (
    <Section label="On probation" action={<Button size="xs" variant="ghost" onClick={onOpenHub}>Hub map</Button>}>
      <Gate load={hub} what="the hub map">
        {h => ("absent" in h
          ? <Absent>The hub map is not on this install.</Absent>
          : h.totals.probation === 0
            ? <Absent>{h.totals.automations === 0
                ? "No automation is declared yet, so none is on probation."
                : `None of ${countNoun(h.totals.automations, "automation")} is on probation.`}</Absent>
            : (
              <div className="aug-item">
                <div className="aug-fs-ui" style={{ color: "var(--t1)" }}>
                  <span className="aug-num" style={{ marginRight: 10 }}>{h.totals.probation}</span>
                  of {countNoun(h.totals.automations, "automation")} on probation
                </div>
                <div className="aug-item-foot aug-fs-sm">
                  <span>Its sends reach its declarer first, and each is marked right or wrong on Departures. The Hub map lists every one with its marks so far.</span>
                </div>
              </div>
            ))}
      </Gate>
    </Section>
  );
}
