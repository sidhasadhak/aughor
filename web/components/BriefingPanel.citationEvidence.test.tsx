// @vitest-environment jsdom
/**
 * A synthesis citation opens onto its evidence.
 *
 * 2026-10-11, luxexperience: the Full synthesis's first claim cited a metric's move, which the Briefing's own list of
 * findings does not hold — so its Evidence opened a stand-in reading "Confidence 0%", "Novelty 0/10" and "— no query
 * recorded —". The move had its query and a confidence of 0.8; the citation dropped both. A citation now carries
 * them, and a figure it does not carry (a brief built before) reads "—", never an invented 0.
 */
import { render, screen } from "@/lib/testing";
import { describe, expect, it } from "vitest";

import { DossierTrace, EvidenceDrawer, findingOfCitation } from "@/components/BriefingPanel";
import type { BriefingCitation, FindingDossier } from "@/lib/api";

const SQL = "SELECT day, SUM(converted) * 1.0 / COUNT(*) AS rate FROM web_sessions GROUP BY day ORDER BY day";
const MOVE: BriefingCitation = {
  ref: "1", insight_id: "metric-move::web_session_conversion_rate", domain: "Key Metrics", angle: "Trend",
  finding: "Web Session Conversion Rate has fallen from 100% to 31% (-69%) over the period.",
  sql: SQL, confidence: 0.8, novelty: 3,
};
const BUILT_BEFORE: BriefingCitation = { ...MOVE, sql: undefined, confidence: undefined, novelty: undefined };

const open = (c: BriefingCitation) =>
  render(<EvidenceDrawer insight={findingOfCitation(c)} domain="Key Metrics" onClose={() => {}} />);

describe("a citation the Briefing's list does not hold", () => {
  it("opens onto the query, confidence and novelty it carries", () => {
    expect(findingOfCitation(MOVE)).toMatchObject({ sql: SQL, confidence: 0.8, novelty: 3 });
    open(MOVE);
    expect(screen.getByText(SQL)).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
    expect(screen.getByText("3/10")).toBeInTheDocument();
    expect(screen.queryByText("— no query recorded —")).toBeNull();
  });

  it("says a figure it does not carry is unknown, never 0", () => {
    open(BUILT_BEFORE);
    expect(screen.queryByText("0%")).toBeNull();
    expect(screen.queryByText("0/10")).toBeNull();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);      // confidence and novelty (freshness too)
    expect(screen.getByText("— no query recorded —")).toBeInTheDocument();
  });

  it("is the Briefing's own finding whenever its list holds it", () => {
    const held = findingOfCitation(BUILT_BEFORE);
    expect(findingOfCitation(MOVE, held)).toBe(held);
  });
});

describe("a derivation's question", () => {
  const base: FindingDossier = {
    dossier_version: 1, question: "How has GMV moved between its first and last whole months?", sql: "SELECT 1",
    finding: "f", rationale: "", result_cells: "", grounding: { grounded: true, checked: 0, ungrounded: [] },
    structural_ctx: { null_meanings: {}, joins: [], lifecycles: {}, distributions: {} },
    generated_at: "", data_fingerprint: null,
  };

  it("is the Briefing's when the Briefing measured it, and the explorer's otherwise", () => {
    const { unmount } = render(<DossierTrace dossier={{ ...base, asked_by: "briefing" }} />);
    expect(screen.getByText("Question the Briefing measured")).toBeInTheDocument();
    unmount();
    render(<DossierTrace dossier={base} />);
    expect(screen.getByText("Question the explorer asked")).toBeInTheDocument();
  });
});
