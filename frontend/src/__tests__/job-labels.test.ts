import { describe, test, expect } from "vitest";
import { nodeLabel, NODE_LABELS } from "@/lib/jobLabels";

describe("nodeLabel (spec §2.2)", () => {
  test("maps_all_seven", () => {
    [
      "ingest_agent",
      "clause_splitter",
      "crag_retrieval",
      "self_rag_validation",
      "risk_score",
      "redline",
      "skip_redline",
      "report",
    ].forEach((n) => expect(NODE_LABELS[n]).toBeTruthy());
    // redline and skip_redline are both logical Node 6 → same label (011 §2.4)
    expect(nodeLabel("redline")).toBe(nodeLabel("skip_redline"));
  });

  test("unknown_falls_back", () => {
    expect(nodeLabel("nope")).toBe("Analyzing…");
    expect(nodeLabel(null)).toBe("Analyzing…");
    expect(nodeLabel(undefined)).toBe("Analyzing…");
  });
});
