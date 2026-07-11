/**
 * Maps the pipeline's internal graph node names (011 §2.4 / builder) to friendly, display-only
 * labels for the processing screen. The canonical names remain the backend's — this is UI text.
 */
export const NODE_LABELS: Record<string, string> = {
  ingest_agent: "Reading & extracting the document",
  clause_splitter: "Breaking the document into clauses",
  crag_retrieval: "Retrieving legal evidence",
  self_rag_validation: "Validating findings",
  risk_score: "Scoring risk",
  redline: "Drafting safer language",
  skip_redline: "Drafting safer language", // both logical Node 6 → same label (011 §2.4)
  report: "Compiling your report",
};

/** Defensive: an unknown/renamed node yields a generic label rather than crashing (spec AC-11). */
export function nodeLabel(node?: string | null): string {
  return (node && NODE_LABELS[node]) || "Analyzing…";
}
