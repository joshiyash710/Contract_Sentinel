import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { ApiError } from "@/lib/api/client";
import { ReportView } from "@/components/report/ReportView";
import {
  makeFakeClient,
  completedFinal,
} from "./_fakeClient";
import {
  ingestErrorReportFixture,
  emptyReportFixture,
} from "@/lib/api/fixtures";

const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace }) }));
vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));

beforeEach(() => {
  push.mockReset();
  replace.mockReset();
  vi.mocked(getApiClient).mockReset();
});

/** Expand a collapsed FindingCard by clicking its header button (matched by title). */
async function expandCard(title: RegExp) {
  const header = await screen.findByRole("button", { name: title });
  fireEvent.click(header);
}

describe("ReportView (spec 017 AC-1,3-11, EC-2)", () => {
  test("header_and_downloads", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportView jobId="job-1" />);

    expect(await screen.findByText("sample_contract.pdf")).toBeInTheDocument();

    const md = screen.getByRole("link", { name: /markdown/i });
    const json = screen.getByRole("link", { name: /json/i });
    expect(md).toHaveAttribute("href", "/api/jobs/job-1/report?format=md");
    expect(json).toHaveAttribute("href", "/api/jobs/job-1/report?format=json");
  });

  test("derived_band_no_score", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({})); // high:1 → High risk
    render(<ReportView jobId="job-1" />);
    // Exact "High risk" is the derived header band (finding badges read "High Risk").
    expect(await screen.findByText("High risk")).toBeInTheDocument();
    expect(screen.getByText(/1 high · 1 medium · 1 low across 12 clauses/)).toBeInTheDocument();
    // No fabricated 0–100 score anywhere (spec D2/AC-2).
    expect(screen.queryByText(/\/100/)).not.toBeInTheDocument();
  });

  test("ocr_note", async () => {
    // empty fixture has ocr_used:true, confidence 0.87
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ report: emptyReportFixture }));
    render(<ReportView jobId="job-1" />);
    expect(await screen.findByText(/OCR/i)).toBeInTheDocument();
    expect(screen.getByText(/87%/)).toBeInTheDocument();
  });

  test("no_ocr_note_when_unused", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({})); // rich fixture ocr_used:false
    render(<ReportView jobId="job-1" />);
    await screen.findByText("sample_contract.pdf");
    expect(screen.queryByText(/OCR/i)).not.toBeInTheDocument();
  });

  test("findings_render_in_order", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportView jobId="job-1" />);
    const headers = await screen.findAllByTestId("finding-title");
    expect(headers.map((h) => h.textContent)).toEqual([
      "Limitation Of Liability",
      "Indemnification",
      "Governing Law",
      "Clause 4",
    ]);
  });

  test("null_severity_badge", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportView jobId="job-1" />);
    // 4th finding has risk_level:null → "Severity unavailable" (visible in the header).
    expect(await screen.findByText(/severity unavailable/i)).toBeInTheDocument();
  });

  test("rewrite_three_way", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportView jobId="job-1" />);
    // finding 1 (rewritten) is expanded by default → shows the rewrite text.
    expect(
      await screen.findByText(/aggregate liability shall not exceed the total fees/i),
    ).toBeInTheDocument();

    // finding 2 (unavailable) → expand → muted note, no rewrite text.
    await expandCard(/indemnification/i);
    expect(screen.getByText(/couldn.t be generated/i)).toBeInTheDocument();

    // finding 3 (not_eligible) → expand → NO rewrite block at all.
    await expandCard(/governing law/i);
    const card3 = screen.getByText("Governing Law").closest("[data-testid='finding-card']")!;
    expect(within(card3 as HTMLElement).queryByTestId("rewrite-block")).not.toBeInTheDocument();
  });

  test("rationale_and_no_business_impact", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportView jobId="job-1" />);
    expect(await screen.findByText(/caps liability far below the contract value/i)).toBeInTheDocument();
    // finding 4 has risk_rationale:null → expand → muted placeholder.
    await expandCard(/clause 4/i);
    expect(screen.getByText(/no explanation provided/i)).toBeInTheDocument();
    // No fabricated "Business Impact" section anywhere (spec D4).
    expect(screen.queryByText(/business impact/i)).not.toBeInTheDocument();
  });

  test("evidence_list", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportView jobId="job-1" />);
    // finding 1 (expanded) has one evidence row.
    expect(await screen.findByText(/playbook:\/\/liability\/caps/i)).toBeInTheDocument();
    // finding 3 (not_eligible, no evidence) → expand → no "Supporting sources" header.
    await expandCard(/governing law/i);
    const card3 = screen.getByText("Governing Law").closest("[data-testid='finding-card']")!;
    expect(within(card3 as HTMLElement).queryByText(/supporting sources/i)).not.toBeInTheDocument();
  });

  test("long_clause_collapses_and_confidence", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportView jobId="job-1" />);
    // finding 1 confidence 0.82 → "82% confidence" shown.
    expect(await screen.findByText(/82% confidence/i)).toBeInTheDocument();
    // Its long clause is collapsed: the tail text isn't present until "show full clause".
    expect(screen.queryByText(/possibility of such damages arising from any cause whatsoever/i))
      .not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /show full clause/i }));
    expect(
      screen.getByText(/possibility of such damages arising from any cause whatsoever/i),
    ).toBeInTheDocument();
  });

  test("ingest_error_panel", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ report: ingestErrorReportFixture }));
    render(<ReportView jobId="job-1" />);
    expect(await screen.findByText(/couldn.t fully process/i)).toBeInTheDocument();
    expect(screen.getByText(/could not parse the uploaded file/i)).toBeInTheDocument();
    // Not an empty findings list masquerading as success.
    expect(screen.queryByText(/no risky clauses found/i)).not.toBeInTheDocument();
  });

  test("zero_findings_empty_state", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ report: emptyReportFixture }));
    render(<ReportView jobId="job-1" />);
    expect(await screen.findByText(/no risky clauses found/i)).toBeInTheDocument();
    // Distinct from the ingest-error panel.
    expect(screen.queryByText(/couldn.t fully process/i)).not.toBeInTheDocument();
  });

  test("not_found_and_artifact_states", async () => {
    // 404 + unknown job → "report not found" + link to /upload.
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({
        getReportError: new ApiError("x", 404),
        getJobError: new ApiError("no job", 404),
      }),
    );
    const { unmount } = render(<ReportView jobId="job-1" />);
    expect(await screen.findByText(/couldn.t find that report|report not found/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /upload|new analysis/i })).toHaveAttribute(
      "href",
      "/upload",
    );
    unmount();

    // 404 + completed job → "artifact unavailable" (distinct copy).
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({
        getReportError: new ApiError("x", 404),
        statuses: [completedFinal({ status: "completed" })],
      }),
    );
    render(<ReportView jobId="job-2" />);
    expect(await screen.findByText(/no longer available/i)).toBeInTheDocument();
  });

  test("redirecting_on_409", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ getReportError: new ApiError("not ready", 409) }),
    );
    render(<ReportView jobId="job-9" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/jobs/job-9"));
  });
});
