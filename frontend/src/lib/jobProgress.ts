/**
 * Frontend mirror of 011 `progress.py` node→index map (spec 015 D7). Used to derive
 * "Step {index} of {total}" from a polled `JobStatus.current_node` (the poll transport carries
 * `current_node`, not the SSE `index`/`total`). redline & skip_redline are both logical Node 6.
 */
export const NODE_INDEX: Record<string, number> = {
  ingest_agent: 1,
  clause_splitter: 2,
  crag_retrieval: 3,
  self_rag_validation: 4,
  risk_score: 5,
  redline: 6,
  skip_redline: 6,
  report: 7,
};

export const TOTAL_STEPS = 7;

/** Index for a node name, or null for unknown (defensive — a rename won't crash the bar). */
export function nodeIndex(node?: string | null): number | null {
  return node ? NODE_INDEX[node] ?? null : null;
}
