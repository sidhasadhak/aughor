"use client";

import { useCallback, useEffect, useState } from "react";

import { getHubMap, type HubMapResponse, type HubMapRow } from "@/lib/api";
import {
  costCaveat, costText, destinationText, ownerText, probationDetail, probationText,
  stateColor,
} from "@/lib/hubMap";
import { formatDateTime } from "@/lib/format";
import { Term } from "@/components/agentops/Term";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { SkeletonRows } from "@/components/ui/motion";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

const RUN_COLOR: Record<string, string> = {
  fired: "var(--grn3)",
  not_fired: "var(--t3)",
  gated: "var(--amb3)",
  error: "var(--red3)",
  paused: "var(--amb3)",
};

function Mono({ children, tint }: { children: React.ReactNode; tint?: string }) {
  return (
    <span className="aug-fs-xs" style={{
      fontFamily: "var(--font-mono, monospace)",
      color: tint || "var(--t2)", whiteSpace: "nowrap",
    }}>{children}</span>
  );
}

/**
 * HB-6 — the hub-wide map: every automation on one screen, with the seven columns the
 * roadmap names. Last run sits second since 2026-09-25 (asked): a destination's prompt text
 * had pushed it off the right edge, so the one column a reader checks first was never seen. Agent Ops' Map answers this per agent; this panel answers it for the
 * whole hub, from ONE read (`GET /hub/map`). Cost renders as what the server says it
 * is — a floor — and an unmeasured precision renders as "not measured", never 0%.
 */
export function HubMapPanel({ connId, onOpenAgent, onOpenAutomation }: {
  connId?: string;
  /** AO-4 — every raw id on the map is a link when the shell can open it. */
  onOpenAgent?: (agentId: string) => void;
  onOpenAutomation?: (automationId: string) => void;
}) {
  const [data, setData] = useState<HubMapResponse | null>(null);
  const [absent, setAbsent] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    getHubMap(connId)
      .then(d => { setData(d); setAbsent(d === null); })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [connId]);

  useEffect(() => { load(); }, [load]);

  if (loading && !data) {
    return <div style={{ flex: 1, background: "var(--bg-0)", padding: 16 }}><SkeletonRows rows={6} /></div>;
  }

  // An unreadable map is not an empty one (the AgentMap rule).
  if (error) {
    return (
      <div style={{ flex: 1, background: "var(--bg-0)", padding: 24 }}>
        <div className="aug-fs-sm" style={{ color: "var(--amb3)", marginBottom: 10 }}>
          Could not read the hub map — {error}
        </div>
        <Button variant="outline" size="xs" onClick={load}>Retry</Button>
      </div>
    );
  }

  if (absent) {
    return (
      <EmptyState icon="flow" title="No hub map on this API">
        This API predates the hub map door (HB-6). Update the server and reload.
      </EmptyState>
    );
  }

  const rows = data?.rows ?? [];
  const totals = data?.totals;

  return (
    <div style={{ flex: 1, background: "var(--bg-0)", display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div style={{
        display: "flex", alignItems: "baseline", gap: 14, padding: "12px 16px 8px",
        borderBottom: "1px solid var(--b1)",
      }}>
        <span className="aug-fs-ui" style={{ fontWeight: 600, color: "var(--t1)" }}>Every automation, one screen</span>
        {totals && (
          <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            {totals.automations} automations · {totals.live} live · {totals.probation} on probation
            · cost over {data?.window_days}d is a floor
          </span>
        )}
        <span style={{ flex: 1 }} />
        <Button variant="outline" size="xs" onClick={load}>Refresh</Button>
      </div>

      {rows.length === 0 ? (
        <EmptyState icon="flow" title="Nothing on the map yet">
          The map fills as automations are declared — by people, or by an installed
          function pack.
        </EmptyState>
      ) : (
        <div style={{ flex: 1, overflow: "auto", padding: "0 16px 16px" }}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Automation</TableHead>
                <TableHead>Last run</TableHead>
                <TableHead>Trigger</TableHead>
                <TableHead>Destinations</TableHead>
                <TableHead>Grant</TableHead>
                <TableHead>Owner</TableHead>
                <TableHead className="num">Cost</TableHead>
                <TableHead><Term id="probation">Probation</Term></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map(r => (
                <MapRow key={r.id} row={r} onOpenAgent={onOpenAgent} onOpenAutomation={onOpenAutomation} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function MapRow({ row, onOpenAgent, onOpenAutomation }: {
  row: HubMapRow;
  onOpenAgent?: (agentId: string) => void;
  onOpenAutomation?: (automationId: string) => void;
}) {
  const caveat = costCaveat(row.cost);
  const lastAt = formatDateTime(row.last_run.at);
  return (
    <TableRow>
      <TableCell>
        <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
          <span title={row.state} className="aug-fs-xs" style={{ color: stateColor(row.state) }}>●</span>
          {onOpenAutomation ? (
            <Button variant="link" size="xs" onClick={() => onOpenAutomation(row.id)}
              title={row.description || row.name} style={{ padding: 0, height: "auto" }}>
              {row.name}
            </Button>
          ) : (
            <span className="aug-fs-sm" style={{ color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                  title={row.description || row.name}>
              {row.name}
            </span>
          )}
        </div>
        <div className="aug-fs-xs" style={{ color: "var(--t3)", paddingLeft: 15 }}>{row.conn_id}{row.state !== "live" ? ` · ${row.state}` : ""}</div>
      </TableCell>
      <TableCell>
        {row.last_run.status ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            <span className="aug-fs-sm aug-num" style={{ color: "var(--t1)", whiteSpace: "nowrap" }}
                  title={row.last_run.at || undefined}>{lastAt}</span>
            <span className="aug-fs-xs" style={{ color: RUN_COLOR[row.last_run.status] || "var(--t3)" }}>
              ● {row.last_run.status}
            </span>
          </div>
        ) : <Mono tint="var(--t3)">never</Mono>}
      </TableCell>
      <TableCell>
        <Mono>
          <span title={row.trigger.join(" · ")}
                style={{ display: "block", maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis" }}>
            {row.trigger.join(" · ")}
          </span>
        </Mono>
      </TableCell>
      <TableCell>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {row.destinations.map((d, i) => (
            <Mono key={i} tint={d.routed_about ? "var(--cyn3)" : undefined}>
              <span title={d.resolved?.map(x => x.principal).join(", ") || d.target}
                    style={{ display: "block", maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis" }}>
                {destinationText(d)}
              </span>
            </Mono>
          ))}
        </div>
      </TableCell>
      <TableCell>
        {row.grants.length === 0 ? <Mono tint="var(--t3)">—</Mono> : (
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {row.grants.map(g => (
              <Mono key={g.id}>
                <span title={`${g.action_id} · used ${g.use_count}×`}>
                  {g.action_id.split(":")[0]}→{g.target_value}
                </span>
              </Mono>
            ))}
          </div>
        )}
      </TableCell>
      <TableCell>
        <Mono tint={row.owner.declared_by.startsWith("pack:") ? "var(--vio3)" : undefined}>
          {ownerText(row.owner)}
        </Mono>
        {row.owner.agent_id && (
          <div className="aug-fs-xs" style={{ color: "var(--t3)" }}>
            runs as{" "}
            {onOpenAgent ? (
              <Button variant="link" size="xs" onClick={() => onOpenAgent(row.owner.agent_id)}
                title="Open this agent" style={{ padding: 0, height: "auto" }}>
                {row.owner.agent_id}
              </Button>
            ) : row.owner.agent_id}
          </div>
        )}
      </TableCell>
      <TableCell className="num">
        <span title={caveat || `${row.cost.runs} runs · ${row.cost.deep_runs} deep runs in ${row.cost.window_days}d`}
              className="aug-fs-xs" style={{ color: "var(--t2)" }}>
          {costText(row.cost)}{caveat ? "*" : ""}
        </span>
      </TableCell>
      <TableCell>
        <span title={probationDetail(row.probation)}
              className="aug-fs-xs" style={{ color: row.probation.on ? "var(--amb3)" : "var(--t3)" }}>
          {probationText(row.probation)}
        </span>
      </TableCell>
    </TableRow>
  );
}
