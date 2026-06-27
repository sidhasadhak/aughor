"use client";

import { useEffect, useState } from "react";
import {
  getPacks, proposePackBindings, bindPack, evaluatePack, getPackDeltas, setPackDeltaStatus,
  getConnections, getCatalogTree,
  type PackSummary, type BindingCandidateDTO, type PackDeltaDTO,
} from "@/lib/api";

// Deploy console for Specialist Packs: propose → bind/verify → evaluate → activate, plus the
// flywheel "expert changelog" (accept/dismiss proposed learnings). Self-contained.
export function PacksManager() {
  const [enabled, setEnabled] = useState(false);
  const [packs, setPacks] = useState<PackSummary[]>([]);
  const [sel, setSel] = useState<string | null>(null);

  useEffect(() => {
    getPacks().then(r => { setEnabled(r.enabled); setPacks(r.packs); }).catch(() => {});
  }, []);

  if (packs.length === 0) return null;

  return (
    <div className="mb-5">
      <p className="text-[11px] uppercase tracking-widest text-zinc-500 mb-2">
        Specialist packs{enabled ? "" : " · flag off (gated)"}
      </p>
      <div className="bg-white/[0.03] rounded-lg divide-y divide-white/5">
        {packs.map(p => (
          <div key={p.id} className="px-3 py-2">
            <button onClick={() => setSel(sel === p.id ? null : p.id)}
              className="w-full flex items-center justify-between gap-3 text-left">
              <span className="flex items-center gap-2">
                <span className="text-xs text-zinc-200">{p.name || p.id}</span>
                <Badge color={p.status === "active" ? "#46b06a" : p.status === "deprecated" ? "#888" : "#d4a72c"}>
                  {p.status || "draft"}
                </Badge>
                <Badge color={p.ok ? "#46b06a" : "#e5534b"}>{p.ok ? "valid" : "invalid"}</Badge>
              </span>
              <span className="text-[11px] text-zinc-500">
                {(p.metrics ?? 0)}m · {(p.roles ?? 0)}r · {(p.evals ?? 0)}e {sel === p.id ? "▾" : "▸"}
              </span>
            </button>
            {sel === p.id && <PackDeploy packId={p.id} />}
          </div>
        ))}
      </div>
    </div>
  );
}

function Badge({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <span className="text-[9.5px] font-mono px-1 py-0.5 rounded"
      style={{ background: "var(--bg-1)", color }}>{children}</span>
  );
}

function PackDeploy({ packId }: { packId: string }) {
  const [conns, setConns] = useState<{ id: string; name: string }[]>([]);
  const [conn, setConn] = useState("");
  const [schemas, setSchemas] = useState<string[]>([]);
  const [schema, setSchema] = useState("");
  const [proposals, setProposals] = useState<Record<string, BindingCandidateDTO> | null>(null);
  const [fullyGroundable, setFullyGroundable] = useState(false);
  const [verified, setVerified] = useState<boolean | null>(null);
  const [evalRes, setEvalRes] = useState<Awaited<ReturnType<typeof evaluatePack>> | null>(null);
  const [deltas, setDeltas] = useState<PackDeltaDTO[]>([]);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    getConnections().then(cs => {
      const list = cs.map(c => ({ id: c.id, name: c.name }));
      setConns(list);
      if (list[0]) setConn(list[0].id);
    }).catch(() => {});
    getPackDeltas(packId).then(setDeltas).catch(() => {});
  }, [packId]);

  useEffect(() => {
    if (!conn) return;
    getCatalogTree().then(tree => {
      const entry = tree.sections.flatMap(s => s.entries).find(e => e.conn_id === conn);
      const names = entry?.schemas.map(s => s.name) ?? [];
      setSchemas(names);
      setSchema(names[0] ?? "");
    }).catch(() => setSchemas([]));
  }, [conn]);

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label); setErr("");
    try { await fn(); } catch (e) { setErr(e instanceof Error ? e.message : "failed"); }
    setBusy("");
  };

  const propose = () => run("propose", async () => {
    setVerified(null); setEvalRes(null);
    const r = await proposePackBindings(packId, conn, schema || undefined, "");
    setProposals(r.proposals); setFullyGroundable(r.fully_groundable);
  });

  const deploy = () => run("deploy", async () => {
    const bindings: Record<string, unknown> = {};
    for (const [role, c] of Object.entries(proposals || {})) {
      bindings[role] = { table: c.table, column: c.column, value: c.value, confidence: c.confidence };
    }
    const r = await bindPack(packId, conn, bindings, schema || undefined);
    setVerified(r.verified);
  });

  const evaluate = () => run("evaluate", async () => {
    setEvalRes(await evaluatePack(packId, conn, schema || undefined));
  });

  const judgeDelta = async (id: number, status: "accepted" | "dismissed") => {
    await setPackDeltaStatus(id, status);
    setDeltas(ds => ds.filter(d => d.id !== id));
  };

  const inp = "text-[11px] bg-[var(--bg-2)] border border-[var(--b1)] rounded px-2 py-1 text-zinc-300";
  const btn = "text-[11px] px-2 py-1 rounded border border-zinc-700 text-zinc-300 hover:bg-white/5 disabled:opacity-40";

  return (
    <div className="mt-2 pl-1 space-y-3">
      {/* Deploy controls */}
      <div className="flex flex-wrap items-center gap-2">
        <select value={conn} onChange={e => setConn(e.target.value)} className={inp} aria-label="Connection">
          {conns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={schema} onChange={e => setSchema(e.target.value)} className={inp} aria-label="Schema">
          {schemas.length === 0 && <option value="">(schema)</option>}
          {schemas.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <button className={btn} disabled={!conn || busy !== ""} onClick={propose}>
          {busy === "propose" ? "Proposing…" : "1 · Propose bindings"}
        </button>
        <button className={btn} disabled={!proposals || busy !== ""} onClick={deploy}>
          {busy === "deploy" ? "Binding…" : "2 · Bind + verify"}
        </button>
        <button className={btn} disabled={verified !== true || busy !== ""} onClick={evaluate}
          title={verified !== true ? "Deploy first: run Bind + verify" : ""}>
          {busy === "evaluate" ? "Evaluating…" : "3 · Evaluate"}
        </button>
      </div>
      <p className="text-[10px] text-zinc-600">Deploy a pack: propose → bind + verify → evaluate → (set status active + enable the flag to steer runs).</p>
      {err && <p className="text-[11px] text-rose-400">{err}</p>}

      {/* Step 1 — groundability (a PROPOSAL, not a deployment) */}
      {proposals && (() => {
        const total = Object.keys(proposals).length;
        const groundable = Object.values(proposals).filter(c => c.bound).length;
        return (
          <div className="text-[11px]">
            <div className="text-zinc-500 mb-1">
              Proposed bindings — {fullyGroundable
                ? <span className="text-emerald-400">all {total} roles groundable</span>
                : <span className="text-amber-400">{groundable}/{total} roles groundable</span>}
              {verified !== null && (verified
                ? <span className="text-emerald-400"> · deployed ✓ verified</span>
                : <span className="text-rose-400"> · pinned but not verified</span>)}
            </div>
            <div className="font-mono space-y-0.5">
              {Object.entries(proposals).map(([role, c]) => (
                <div key={role} className="flex justify-between gap-3">
                  <span className="text-zinc-300">{role}</span>
                  <span className={c.bound ? "text-zinc-400" : "text-rose-400"}>
                    {c.value || `${c.table ?? "?"}.${c.column ?? "?"}`} <span className="text-zinc-600">({Math.round(c.confidence * 100)}%)</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        );
      })()}

      {/* Step 3 — evals (pass/fail) shown SEPARATELY from activation readiness */}
      {evalRes && (
        <div className="text-[11px] space-y-1">
          <div className="text-zinc-500">
            Evals — {evalRes.pass_rate != null
              ? <span className={evalRes.pass_rate === 1 ? "text-emerald-400" : "text-amber-400"}>{Math.round(evalRes.pass_rate * 100)}% pass</span>
              : "not run"}
          </div>
          {evalRes.results.map((r, i) => (
            <div key={i} className="flex gap-2">
              <span className={r.passed ? "text-emerald-400" : "text-rose-400"}>{r.passed ? "✓" : "✗"}</span>
              <span className="text-zinc-400">{r.question}</span>
            </div>
          ))}
          <div className="text-zinc-500 pt-0.5">
            Activation — {evalRes.can_activate
              ? <span className="text-emerald-400">ready ✓</span>
              : <span className="text-amber-400">blocked</span>}
          </div>
          {evalRes.reasons.map((r, i) => <p key={i} className="text-amber-400/80 pl-3">· {r}</p>)}
        </div>
      )}

      {/* Flywheel changelog */}
      {deltas.length > 0 && (
        <div className="text-[11px]">
          <div className="text-zinc-500 mb-1">Expert changelog — {deltas.length} proposed learning(s)</div>
          {deltas.map(d => (
            <div key={d.id} className="flex items-start justify-between gap-2 py-1 border-b border-white/5 last:border-0">
              <span className="text-zinc-400">
                <span className="text-zinc-500">[{d.kind}{d.target ? ` ${d.target}` : ""}]</span> {d.content}
              </span>
              <span className="shrink-0 flex gap-1">
                <button className={btn} onClick={() => judgeDelta(d.id, "accepted")}>Accept</button>
                <button className={btn} onClick={() => judgeDelta(d.id, "dismissed")}>Dismiss</button>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
