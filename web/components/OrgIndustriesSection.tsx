"use client";

/**
 * OrgIndustriesSection — Settings ▸ Organization: "Industries" (IP-2).
 *
 * The question the installer asked, asked again: which industry packages this deployment reads.
 * "Every industry" keeps them all, and Aughor works out each connection's industry from its data.
 * "Only these" keeps the ticked ones: a connection whose industry is not among them reads only the
 * knowledge every industry shares. It is the same choice `aughor industries` changes — one file on the
 * server — and deployment-wide, so the panel shows it at app scope only.
 *
 * Saving can drop stored business profiles whose industry now resolves differently; each is rebuilt,
 * with a model call, the next time its data is used, and the section says how many.
 */
import { useEffect, useState } from "react";
import { getIndustryChoice, updateIndustryChoice, type IndustryChoice } from "@/lib/api";
import { Button } from "@/components/ui/button";

// Sizes come from the aug-fs-* classes (the design-token gate holds raw font sizes where they are).
const hintStyle: React.CSSProperties = { color: "var(--t3)", marginTop: 6 };
const optionStyle: React.CSSProperties = { display: "flex", alignItems: "center", gap: 8, cursor: "pointer" };

const sameIds = (a: string[] | null, b: string[] | null) =>
  a === null || b === null ? a === b : [...a].sort().join(",") === [...b].sort().join(",");

export function OrgIndustriesSection() {
  const [choice, setChoice] = useState<IndustryChoice | null>(null);
  const [every, setEvery] = useState(true);
  const [kept, setKept] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const show = (c: IndustryChoice) => {
    setChoice(c);
    setEvery(c.industries === null);
    setKept(c.industries ?? c.shipped.map((i) => i.id));
  };

  useEffect(() => {
    getIndustryChoice()
      .then(show)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load the industry choice"));
  }, []);

  if (!choice) return error ? <div className="aug-fs-xs" style={{ color: "var(--red4)" }}>{error}</div> : null;
  if (!choice.shipped.length) return null;

  const wanted = every ? null : [...kept].sort();
  const changed = !sameIds(wanted, choice.industries);

  const save = async () => {
    setSaving(true); setError(""); setNote("");
    try {
      const saved = await updateIndustryChoice(wanted);
      show(saved);
      const n = saved.profiles_refreshed;
      setNote(n > 0
        ? `Saved. ${n} business ${n === 1 ? "profile" : "profiles"} will be rebuilt the next time ${n === 1 ? "its" : "their"} data is used.`
        : "Saved ✓");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save the industry choice");
    } finally {
      setSaving(false);
    }
  };

  const pick = (next: boolean) => { setNote(""); setEvery(next); };
  const toggle = (id: string, on: boolean) => {
    setNote("");
    setKept((prev) => (on ? [...prev, id] : prev.filter((k) => k !== id)));
  };

  return (
    <div>
      <div className="aug-label" style={{ marginBottom: 10 }}>Industries</div>
      <div role="radiogroup" aria-label="Industries" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <label className="aug-fs-sm" style={optionStyle}>
          <input type="radio" name="industries" checked={every} onChange={() => pick(true)} style={{ cursor: "pointer" }} />
          Every industry
        </label>
        <label className="aug-fs-sm" style={optionStyle}>
          <input type="radio" name="industries" checked={!every} onChange={() => pick(false)} style={{ cursor: "pointer" }} />
          Only these
        </label>
      </div>
      {!every && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 10, paddingLeft: 22 }}>
          {choice.shipped.map((industry) => (
            <label key={industry.id} className="aug-fs-sm" style={optionStyle} title={industry.description || undefined}>
              <input
                type="checkbox"
                checked={kept.includes(industry.id)}
                onChange={(e) => toggle(industry.id, e.target.checked)}
                style={{ cursor: "pointer" }}
              />
              {industry.name}
            </label>
          ))}
        </div>
      )}
      <div className="aug-fs-xs" style={hintStyle}>
        {every
          ? "Aughor reads every industry package and works out each connection's industry from its data."
          : kept.length === 0
            ? "No industry package: every connection uses only the knowledge all industries share."
            : "A connection whose industry is not ticked uses only the knowledge all industries share."}
      </div>
      {choice.ignored.length > 0 && (
        <div className="aug-fs-xs" style={hintStyle}>Ignored, because no package carries it: {choice.ignored.join(", ")}</div>
      )}
      {choice.problem && <div className="aug-fs-xs" style={hintStyle}>{choice.problem}</div>}
      {error && <div className="aug-fs-xs" style={{ ...hintStyle, color: "var(--red4)" }}>{error}</div>}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10 }}>
        <Button variant="secondary" size="sm" onClick={save} disabled={saving || !changed}>
          {saving ? "Saving…" : "Save industries"}
        </Button>
        {note && !saving && <span className="aug-fs-xs" style={{ color: "var(--grn4)" }}>{note}</span>}
      </div>
    </div>
  );
}
