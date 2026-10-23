"use client";

/**
 * "Keep on a dashboard" — a Data Canvas answer's question kept as a Question on one of the person's dashboards (PENDING
 * 54; design-mockups/dashboard-questions.html, screen 2, approved 2026-10-23). The answer is its first; the agent
 * answers it again on the rhythm chosen. "Pin to dashboard" beside it still pins just the answer's query.
 *
 * If keeping the dashboard is refused after the question was kept, its automation is switched off at once, so nothing
 * asks — and spends — for a question no dashboard shows.
 */
import { useEffect, useState } from "react";

import { QuestionComposer } from "@/components/dashboards/QuestionComposer";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/select";
import { getDashboard, getSystemFlags, keepDashboard, listDashboards, setAutomationEnabled, type DashboardListed, type QuestionRhythm } from "@/lib/api";
import { placeQuestion } from "@/lib/dashboards/edit";
import { requestTab } from "@/lib/navigate";

export function KeepOnDashboard({ connectionId, schema, question, runId }: {
  connectionId: string;
  schema?: string;
  /** The answer's question, as the person asked it. */
  question: string;
  /** The finished answer it is kept from: its first. */
  runId: string;
}) {
  const [on, setOn] = useState(false);
  const [open, setOpen] = useState(false);
  const [mine, setMine] = useState<{ id: string; title: string }[] | null>(null);
  const [chosen, setChosen] = useState("");
  const [said, setSaid] = useState("");
  useEffect(() => {
    let alive = true;
    getSystemFlags().then(f => { if (alive) setOn(!!f["dashboard.questions"]?.value && !!f["dashboard.composed"]?.value); })
      .catch(() => { if (alive) setOn(false); });
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    if (!open) return;
    let alive = true;
    listDashboards(connectionId).then(l => {
      if (!alive) return;
      // the server's field names are the stored ones (GLOSSARY, frozen names); read once, here
      const standing = (l?.cockpits ?? []).filter((d: DashboardListed) => !d.retired).map(d => ({ id: d.cockpit_id, title: d.title }));
      setMine(standing);
      setChosen(standing[0]?.id ?? "");
    }).catch(() => { if (alive) setMine([]); });
    return () => { alive = false; };
  }, [open, connectionId]);
  if (!on) return null;

  const place = async (automation: string, first: string, rhythm: QuestionRhythm) => {
    const title = mine?.find(d => d.id === chosen)?.title ?? "your dashboard";
    try {
      const now = await getDashboard(connectionId, chosen);
      const out = await keepDashboard(connectionId, chosen, placeQuestion(now.cockpit.spec, automation, first || undefined),
        "a question kept from the Data Canvas");
      if (out.kept) {
        setSaid(`Kept on “${title}”. ${rhythm === "ask" ? "It is asked there only when you ask." : "It is answered there on its rhythm."}`);
        setOpen(false);
        return;
      }
      await setAutomationEnabled(automation, false).catch(() => undefined);
      setSaid(`Not kept on “${title}”: ${out.sentences.join(" ")}`);
    } catch (e) {
      await setAutomationEnabled(automation, false).catch(() => undefined);
      setSaid(`Not kept: ${(e as Error).message}`);
    }
  };

  return (
    <div style={{ display: "contents" }}>
      {!open && (
        <Button variant="ghost" size="xs" data-testid="keep-on-dashboard" onClick={() => { setOpen(true); setSaid(""); }}
          title="Keep this question on one of your dashboards: the agent answers it again on a rhythm, as it did here"
          className="h-auto px-2.5 py-1 aug-fs-xs font-normal">
          Keep on a dashboard
        </Button>
      )}
      {said && <span className="aug-fs-xs" data-testid="keep-on-dashboard-said" style={{ color: "var(--t2)" }}>{said}</span>}
      {open && (
        <div style={{ flexBasis: "100%", marginTop: 8 }}>
          {mine === null ? (
            <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>Reading your dashboards…</span>
          ) : mine.length === 0 ? (
            <div className="aug-fs-sm" style={{ color: "var(--t2)", display: "flex", gap: 8, alignItems: "center" }}>
              You have no dashboard on this connection yet.
              <Button size="xs" variant="secondary" onClick={() => requestTab("dashboards", { conn: connectionId })}>Start one</Button>
              <Button size="xs" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            </div>
          ) : (
            <>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
                <span className="aug-fs-xs" style={{ color: "var(--t2)" }}>Dashboard</span>
                <SelectField value={chosen} aria-label="The dashboard to keep it on" onChange={e => setChosen(e.target.value)}
                  style={{ maxWidth: 280 }}>
                  {mine.map(d => <option key={d.id} value={d.id}>{d.title}</option>)}
                </SelectField>
              </div>
              <QuestionComposer connectionId={connectionId} schema={schema} question={question} firstRun={runId}
                from="From the Data Canvas · this answer" onClose={() => setOpen(false)}
                onKept={(automation, first, rhythm) => void place(automation, first, rhythm)} />
            </>
          )}
        </div>
      )}
    </div>
  );
}
