"use client";

/**
 * Where a pack is installed, the version installed there, and what upgrading to the pack's version brings (Arc FA,
 * FA-6, flag `packs.installed_versions`; `aughor/packs/upgrade.py`). Drawn under a pack in System → Packs only while
 * the flag is on — the parent reads it — and the routes answer 404 otherwise, when this draws nothing at all.
 *
 * The diff is the server's: items added, changed and removed since the installed version, each one a person declined
 * marked "you declined this in vN", and the unchanged ones they declined, which stay declined. Upgrading proposes only
 * the new and changed — what it proposes is said beside each item, and so is why it proposes nothing for the rest.
 */
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";
import {
  getConnections, getPackInstalls, getPackUpgrade, upgradePack,
  type PackInstall, type PackOfferedItem, type PackUpgradeDiff,
} from "@/lib/api";
import { countNoun } from "@/lib/format";

const KIND_WORD: Record<PackOfferedItem["kind"], string> = {
  term: "term", alert: "alert", metric: "metric", structure: "structure",
};

/** The one line an install row says about its version. */
export function versionLine(install: Pick<PackInstall, "installed" | "recorded" | "behind">, available: number): string {
  if (!install.recorded) return `installed before versions were kept · v${available} available`;
  if (available > install.installed) return `installed v${install.installed} · v${available} available`;
  return `installed v${install.installed} · up to date`;
}

/** How an item a person declined is marked. */
export function declinedMark(item: Pick<PackOfferedItem, "declined" | "declined_in">): string {
  if (!item.declined) return "";
  return item.declined_in != null ? `you declined this in v${item.declined_in}` : "you declined this";
}

function ItemRow({ item }: { item: PackOfferedItem }) {
  const mark = declinedMark(item);
  return (
    <li data-testid="pack-upgrade-item" data-key={item.key} style={{ display: "flex", gap: 8, alignItems: "baseline", padding: "2px 0" }}>
      <span className="aug-fs-xs" style={{ color: "var(--t3)", minWidth: 64 }}>{KIND_WORD[item.kind]}</span>
      <span className="aug-fs-xs" style={{ color: "var(--t1)", minWidth: 0 }}>
        {item.label}
        {item.was ? <span style={{ color: "var(--t3)" }}> · {item.was} → {item.said}</span>
          : item.said ? <span style={{ color: "var(--t3)" }}> · {item.said}</span> : null}
        {mark && <span data-testid="pack-upgrade-declined" style={{ color: "var(--amb4)" }}> · {mark}</span>}
      </span>
      <span className="aug-fs-xs" style={{ marginLeft: "auto", color: item.will_offer ? "var(--accent-11)" : "var(--t3)", whiteSpace: "nowrap" }}
        title={item.why}>
        {item.will_offer ? "proposed on upgrade" : item.why}
      </span>
    </li>
  );
}

function Group({ title, items }: { title: string; items: PackOfferedItem[] }) {
  if (!items.length) return null;
  return (
    <div style={{ marginTop: 6 }}>
      <div className="aug-fs-xs" style={{ color: "var(--t2)", fontWeight: 600 }}>{title} · {items.length}</div>
      <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }}>
        {items.map(i => <ItemRow key={i.key} item={i} />)}
      </ul>
    </div>
  );
}

function UpgradeDiff({ packId, install, available, connName, onUpgraded }: {
  packId: string; install: PackInstall; available: number; connName: string; onUpgraded: () => void;
}) {
  const [diff, setDiff] = useState<PackUpgradeDiff | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    getPackUpgrade(packId, install.connection_id, install.schema || undefined)
      .then(d => { if (live) setDiff(d); })
      .catch(e => { if (live) setErr((e as Error).message); });
    return () => { live = false; };
  }, [packId, install.connection_id, install.schema]);

  const upgrade = async () => {
    setBusy(true);
    try {
      const out = await upgradePack(packId, install.connection_id, install.schema || undefined);
      const staged = out.alerts.staged?.length ?? 0;
      toast.success(`Upgraded ${connName} to v${out.to}`, {
        description: `Proposed ${countNoun(out.terms.proposed ?? 0, "term")} and ${countNoun(staged, "alert")}`
          + (out.kept_declined ? `; ${countNoun(out.kept_declined, "item")} you declined stay declined.` : "."),
      });
      onUpgraded();
    } catch (e) {
      toast.error("The upgrade did not go through", { description: (e as Error).message.slice(0, 200) });
    } finally { setBusy(false); }
  };

  if (err) return <p className="aug-fs-xs" style={{ color: "var(--red4)" }}>{err}</p>;
  if (!diff) return <p className="aug-fs-xs" style={{ color: "var(--t3)" }}>Reading what changed…</p>;
  const nothing = !diff.added.length && !diff.changed.length && !diff.removed.length;
  return (
    <div data-testid="pack-upgrade-diff" style={{ marginTop: 6, paddingLeft: 8, borderLeft: "1px solid var(--b1)" }}>
      {diff.note && <p className="aug-fs-xs" style={{ color: "var(--t3)", margin: "0 0 4px" }}>{diff.note}</p>}
      {nothing && <p className="aug-fs-xs" style={{ color: "var(--t3)", margin: 0 }}>Nothing was added, changed or removed since v{diff.installed}.</p>}
      <Group title="Added" items={diff.added} />
      <Group title="Changed" items={diff.changed} />
      <Group title="Removed" items={diff.removed} />
      <Group title="Declined, and unchanged — they stay declined" items={diff.kept_declined} />
      {Object.entries(diff.not_read).map(([what, why]) => (
        <p key={what} className="aug-fs-xs" style={{ color: "var(--t3)", margin: "4px 0 0" }}>Not read ({what}): {why}</p>
      ))}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
        <Button size="xs" data-testid="pack-upgrade-apply" disabled={busy || !diff.upgrade_available} onClick={() => void upgrade()}>
          {busy ? "Upgrading…" : `Upgrade to v${available}`}
        </Button>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>
          {diff.upgrade_available
            ? `Proposes ${countNoun(diff.will_offer, "item")} for you to confirm; nothing you declined comes back unchanged.`
            : "Up to date."}
        </span>
      </div>
    </div>
  );
}

export function PackInstalls({ packId }: { packId: string }) {
  const [data, setData] = useState<{ available: number; installs: PackInstall[] } | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick(t => t + 1), []);

  useEffect(() => {
    let live = true;
    getPackInstalls(packId).then(d => { if (live) setData(d); }).catch(() => { if (live) setData(null); });
    return () => { live = false; };
  }, [packId, tick]);
  useEffect(() => {
    let live = true;
    getConnections().then(cs => { if (live) setNames(Object.fromEntries(cs.map(c => [c.id, c.name]))); }).catch(() => {});
    return () => { live = false; };
  }, []);

  if (!data) return null;
  return (
    <div data-testid="pack-installs" style={{ marginTop: 8 }}>
      <div className="aug-fs-xs" style={{ color: "var(--t3)", marginBottom: 4 }}>
        Installed on {countNoun(data.installs.length, "connection")} · the pack is at v{data.available}
      </div>
      {data.installs.map(i => {
        const id = `${i.connection_id}/${i.schema}`;
        const name = names[i.connection_id] || i.connection_id;
        return (
          <div key={id} data-testid="pack-install" style={{ padding: "4px 0", borderTop: "1px solid var(--b1)" }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <span className="aug-fs-xs" style={{ color: "var(--t1)" }}>{name}{i.schema ? ` · ${i.schema}` : ""}</span>
              <span className="aug-fs-xs" data-testid="pack-install-version"
                style={{ color: i.behind ? "var(--accent-11)" : "var(--t3)" }}>{versionLine(i, data.available)}</span>
              {i.bound_by && <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>bound by {i.bound_by.replace(/^user:/, "")}</span>}
              <Button size="xs" variant="ghost" style={{ marginLeft: "auto" }} data-testid="pack-install-open"
                onClick={() => setOpen(open === id ? null : id)}>
                {open === id ? "Hide what changed" : i.behind ? "What changed" : "Check"}
              </Button>
            </div>
            {open === id && (
              <UpgradeDiff packId={packId} install={i} available={data.available} connName={name}
                onUpgraded={() => { setOpen(null); reload(); }} />
            )}
          </div>
        );
      })}
    </div>
  );
}
