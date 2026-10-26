"use client";

/**
 * New dashboard → From a pack template (Arc FA, FA-6, flag `packs.dashboard_templates`; `aughor/packs/templates.py`).
 * The templates of the packs bound on this connection, each card saying whether this connection can make it. Drafting
 * one asks no model: the server stages it as one proposal, a card whose metric the connection lacks left out and said,
 * and the person keeps it in the draft review beside every other draft. Drawn only while the flag is on; the list's
 * route answers 404 otherwise, and this says nothing is offered.
 */
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";
import { draftFromPackTemplate, listPackTemplates, type PackTemplate, type PackTemplateDrafted } from "@/lib/api";
import { countNoun } from "@/lib/format";

export function PackTemplatePicker({ connectionId, schema, disabled, onDrafted }: {
  connectionId: string;
  schema?: string;
  disabled?: boolean;
  onDrafted: (out: PackTemplateDrafted) => void | Promise<void>;
}) {
  const [listed, setListed] = useState<{ templates: PackTemplate[]; waiting: Record<string, string> } | null | undefined>(undefined);
  const [busy, setBusy] = useState("");
  useEffect(() => {
    let live = true;
    listPackTemplates(connectionId, schema)
      .then(l => { if (live) setListed(l); })
      .catch(() => { if (live) setListed(null); });
    return () => { live = false; };
  }, [connectionId, schema]);

  const draft = async (t: PackTemplate) => {
    const key = `${t.pack}/${t.id}`;
    setBusy(key);
    try {
      await onDrafted(await draftFromPackTemplate(t.pack, t.id, connectionId, schema));
    } catch (e) {
      toast.error("The template was not drafted", { description: (e as Error).message.slice(0, 200) });
    } finally { setBusy(""); }
  };

  if (listed === undefined) return <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>Reading the pack templates…</span>;
  const templates = listed?.templates ?? [];
  const waiting = Object.entries(listed?.waiting ?? {});
  return (
    <div data-testid="dashboard-new-pack-templates" style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 760 }}>
      {templates.length === 0 && (
        <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>
          No pack bound to this connection offers a dashboard template.
        </span>
      )}
      {templates.map(t => {
        const key = `${t.pack}/${t.id}`;
        const left = t.cards.filter(c => !c.ready);
        return (
          <div key={key} data-testid="dashboard-pack-template" style={{ border: "1px solid var(--b1)", borderRadius: "var(--r3)", padding: "8px 10px" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
              <span className="aug-fs-sm" style={{ color: "var(--t1)", fontWeight: 500 }}>{t.title}</span>
              <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{t.pack_name} pack · v{t.version}</span>
              <Button size="xs" style={{ marginLeft: "auto" }} data-testid="dashboard-pack-template-draft"
                disabled={disabled || !!busy || t.ready === 0} onClick={() => void draft(t)}>
                {busy === key ? "Drafting…" : "Draft it"}
              </Button>
            </div>
            {t.description && <div className="aug-fs-xs" style={{ color: "var(--t2)", marginTop: 2 }}>{t.description}</div>}
            <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 4 }}>
              {countNoun(t.ready, "card")} this connection can make
              {left.length > 0 && <> · left out: {left.map(c => `${c.title} (${c.why})`).join("; ")}</>}
            </div>
          </div>
        );
      })}
      {waiting.map(([pack, why]) => (
        <span key={pack} className="aug-fs-xs" style={{ color: "var(--t3)" }}>{pack}: {why}</span>
      ))}
      <span className="aug-fs-sm" style={{ color: "var(--t3)" }}>No model is asked. Nothing is kept until you keep it.</span>
    </div>
  );
}
