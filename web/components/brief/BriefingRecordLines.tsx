"use client";

/**
 * What the Record adds to the head of the Briefing (the 2027 study §V, screen 3): the mission
 * line — each active mission's objective against its baseline, read first — then the inquiries
 * that are waiting on days to settle, each with the date it will speak, and the predictions in
 * play, each with the day it is scored.
 *
 * A mission reports on its own cadence, so its line states the period it was judged over rather
 * than borrowing the Briefing's range. A connection with no mission says so: the ranking below
 * is then by size alone.
 */
import { requestTab } from "@/lib/navigate";
import {
  getMissionReport, listClaims, listInquiries, listMissions, verdictWords,
  type Claim, type Inquiry, type Mission, type MissionReport,
} from "@/lib/record";
import { day, dayDistance, daysUntil, useLoad } from "@/components/record/kit";
import { objectiveLine } from "@/components/missions/MissionsPanel";
import { StatusChip, type ChipHue } from "@/components/brief/StatusChip";
import { Button } from "@/components/ui/button";

interface Lines {
  missions: { mission: Mission; report: MissionReport | null }[];
  waiting: Inquiry[];
  predictions: Claim[];
}

async function readLines(connectionId: string): Promise<Lines> {
  const [missions, waiting, predictions] = await Promise.all([
    listMissions({ connection_id: connectionId, state: "active" }),
    listInquiries({ connection_id: connectionId, state: "waiting" }),
    listClaims({ connection_id: connectionId, kind: "prediction", state: "open", limit: 20 }),
  ]);
  const reports = await Promise.all(
    missions.map(m => getMissionReport(m.id, true).then(r => r.report).catch(() => null)));
  return { missions: missions.map((mission, i) => ({ mission, report: reports[i] })), waiting, predictions };
}

/** When a prediction is scored — or that its day has come and no score is booked yet. */
function settleWords(settlesOn: string): string {
  if (!settlesOn) return "";
  const n = daysUntil(settlesOn);
  return n !== null && n < 0
    ? ` · its day came on ${day(settlesOn)}; it is scored once that range settles`
    : ` · scored on ${day(settlesOn)}`;
}

const VERDICT_HUE: Record<string, ChipHue> = {
  ahead: "positive", on_track: "positive", met: "positive", moved: "positive",
  behind: "negative", worse: "negative", no_effect: "caution", cannot_tell: "muted",
};

export function BriefingRecordLines({ connectionId }: { connectionId: string }) {
  const load = useLoad(() => readLines(connectionId), [connectionId]);
  // The Briefing never waits on these lines, and a read that failed leaves the page as it was.
  const lines = load.data;
  if (!lines) return null;
  return (
    <div className="aug-brief-lines" data-testid="briefing-record-lines">
      <div className="aug-brief-line">
        <span className="aug-label">Missions</span>
        <div style={{ minWidth: 0, flex: 1 }}>
          {lines.missions.length === 0 ? (
            <span className="aug-fs-ui" style={{ color: "var(--t3)" }}>
              No mission is written for this connection, so what moved is ranked by size alone.{" "}
              <Button variant="link" size="xs" style={{ padding: 0 }} onClick={() => requestTab("missions")}>Write one</Button>
            </span>
          ) : lines.missions.map(({ mission, report }) => (
            <div key={mission.id} className="aug-brief-line-item">
              <Button variant="link" size="xs" className="aug-ledger-open" onClick={() => requestTab("missions", { id: mission.id })}>
                {mission.name}
              </Button>
              <span className="aug-fs-ui" style={{ color: "var(--t2)" }}>{objectiveLine(mission.objective)}</span>
              {report && (
                <>
                  <StatusChip hue={VERDICT_HUE[report.objective.verdict] ?? "muted"}>{verdictWords(report.objective.verdict)}</StatusChip>
                  <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
                    {report.objective.measurable ? report.objective.why : "its metric has no approved definition to measure against a baseline"}
                    {" · "}{day(report.period.from)} to {day(report.period.to)}
                  </span>
                </>
              )}
            </div>
          ))}
        </div>
      </div>

      {lines.waiting.length > 0 && (
        <div className="aug-brief-line">
          <span className="aug-label">Waiting to speak</span>
          <div style={{ minWidth: 0, flex: 1 }}>
            {lines.waiting.map(q => (
              <div key={q.id} className="aug-brief-line-item">
                <Button variant="link" size="xs" className="aug-ledger-open" onClick={() => requestTab("inquiries", { id: q.id })}>
                  {q.question}
                </Button>
                <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
                  waiting for {q.waiting_for || "its check date"}
                  {q.next_check ? ` · it speaks on ${day(q.next_check)} (${dayDistance(q.next_check)})` : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {lines.predictions.length > 0 && (
        <div className="aug-brief-line">
          <span className="aug-label">Predictions in play</span>
          <div style={{ minWidth: 0, flex: 1 }}>
            {lines.predictions.map(p => (
              <div key={p.id} className="aug-brief-line-item">
                <Button variant="link" size="xs" className="aug-ledger-open" onClick={() => requestTab("claims", { id: p.id })}>
                  {p.statement.text}
                </Button>
                <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
                  {String(p.extra.method ?? "")}{settleWords(String(p.extra.settles_on ?? ""))}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
