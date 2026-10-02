import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { ProcessingView } from "@/components/processing/ProcessingView";
import { makeFakeClient, runningStatusWithClauseProgress } from "./_fakeClient";
import type { ClauseProgress } from "@/lib/api/types";

/**
 * Feature 059 — live per-clause CRAG progress feed on the processing screen. The screen polls
 * GET /jobs/{id} (useJobStatus); when the returned JobStatus carries clause_progress, ProcessingView
 * renders a counter + a rolling feed of recent clauses with their source decision.
 */

const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace }) }));
vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));

beforeEach(() => {
  push.mockReset();
  replace.mockReset();
  vi.mocked(getApiClient).mockReset();
  Element.prototype.scrollIntoView = vi.fn();
});

const CP: ClauseProgress = {
  clauses_done: 7,
  clauses_total: 12,
  web_fallbacks: 2,
  recent: [
    { clause_index: 6, clause_total: 12, clause_type: "liability", retrieval_path: "local_kb", confidence: 0.82 },
    { clause_index: 7, clause_total: 12, clause_type: "indemnification", retrieval_path: "web_fallback", confidence: 0.61 },
  ],
};

describe("ProcessingView live CRAG clause feed (feature 059)", () => {
  test("renders the counter and per-clause source lines (AC-12)", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ statuses: [runningStatusWithClauseProgress(CP)] }),
    );
    render(<ProcessingView jobId="job-1" />);

    // running counter
    expect(await screen.findByText(/7\/12 clauses · 2 web-fallbacks/i)).toBeInTheDocument();
    // per-clause lines — source wording reused from 058
    expect(screen.getByText(/Clause 6\/12 · liability — Local knowledge base \(82%\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Clause 7\/12 · indemnification — Live web search \(61%\)/i)).toBeInTheDocument();
  });

  test("web-fallback line is visually distinguished from local-kb (AC-13)", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ statuses: [runningStatusWithClauseProgress(CP)] }),
    );
    render(<ProcessingView jobId="job-1" />);

    const web = await screen.findByText(/Clause 7\/12 .* Live web search/i);
    const local = screen.getByText(/Clause 6\/12 .* Local knowledge base/i);
    expect(web.className).not.toEqual(local.className); // distinct tone
    expect(web.className).toMatch(/risk-medium/); // emphasized (theme token, no hex)
    expect(web.className).not.toMatch(/#[0-9a-f]{3,6}/i);
  });

  test("node stage progress still advances from current_node (AC-14)", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ statuses: [runningStatusWithClauseProgress(CP)] }),
    );
    render(<ProcessingView jobId="job-1" />);
    // crag_retrieval is stage 3 of 7 → "Step 3 of 7" shown by the existing stage indicator.
    expect(await screen.findByText(/Step 3 of 7/i)).toBeInTheDocument();
  });
});
