import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { ApiError } from "@/lib/api/client";
import { ReportHistoryView } from "@/components/history/ReportHistoryView";
import { makeFakeClient } from "./_fakeClient";
import { emptyJobListFixture } from "@/lib/api/fixtures";
import { formatSubmitted, riskTone, overflowNote } from "@/lib/history";
import type { JobList, JobListItem } from "@/lib/api/types";

vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));

beforeEach(() => vi.mocked(getApiClient).mockReset());

// Small inline fixture with names whose alphabetical order differs from date order, so the
// sort assertion is meaningful (the shared jobListFixture happens to already be name-sorted).
const sortableList: JobList = {
  total: 2,
  items: [
    {
      job_id: "job-z",
      original_filename: "Zebra_terms.pdf",
      status: "completed",
      submitted_at: "2026-01-30T10:00:00Z",
      finished_at: "2026-01-30T10:03:00Z",
      report_available: true,
      risk_band: "low",
      high: 0,
      medium: 0,
      low: 2,
    },
    {
      job_id: "job-a",
      original_filename: "Alpha_terms.pdf",
      status: "completed",
      submitted_at: "2026-01-29T10:00:00Z",
      finished_at: "2026-01-29T10:03:00Z",
      report_available: true,
      risk_band: "high",
      high: 3,
      medium: 0,
      low: 0,
    },
  ],
};

function manyItems(n: number): JobList {
  const items: JobListItem[] = Array.from({ length: n }, (_, i) => ({
    job_id: `job-${i}`,
    original_filename: `contract_${String(i).padStart(3, "0")}.pdf`,
    status: "completed",
    submitted_at: `2026-01-01T00:00:00Z`,
    finished_at: `2026-01-01T00:03:00Z`,
    report_available: true,
    risk_band: "low",
    high: 0,
    medium: 0,
    low: 1,
  }));
  return { total: n, items };
}

describe("history.ts helpers", () => {
  test("formatSubmitted reformats a valid ISO and passes through junk", () => {
    const out = formatSubmitted("2026-01-30T09:00:00Z");
    expect(out).toContain("2026");
    expect(out).not.toBe("2026-01-30T09:00:00Z");
    expect(formatSubmitted("not-a-date")).toBe("not-a-date");
  });

  test("riskTone maps bands to tones", () => {
    expect(riskTone("high")).toBe("danger");
    expect(riskTone("medium")).toBe("warning");
    expect(riskTone("low")).toBe("success");
    expect(riskTone("none")).toBe("neutral");
    expect(riskTone(null)).toBe("neutral");
    expect(riskTone(undefined)).toBe("neutral");
  });

  test("overflowNote only when total exceeds fetched", () => {
    expect(overflowNote(100, 150)).toBe("Showing the most recent 100 of 150.");
    expect(overflowNote(3, 3)).toBeNull();
    expect(overflowNote(100, 50)).toBeNull();
  });
});

describe("ReportHistoryView (spec 021)", () => {
  test("AC-1: renders a row per contract with filename/status; completed shows risk + findings", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportHistoryView />);

    // one row per fixture item (jobListFixture has 3)
    expect(await screen.findByText("MSA_AcmeCorp.pdf")).toBeInTheDocument();
    expect(screen.getByText("NDA_draft.docx")).toBeInTheDocument();
    expect(screen.getByText("vendor_terms.pdf")).toBeInTheDocument();

    // completed row → risk badge + findings counts
    const row = screen.getByText("MSA_AcmeCorp.pdf").closest("tr")!;
    expect(within(row).getByText(/high/i)).toBeInTheDocument();
    expect(within(row).getByText(/H\s*3/)).toBeInTheDocument();
    expect(within(row).getByText(/M\s*1/)).toBeInTheDocument();
    expect(within(row).getByText(/L\s*2/)).toBeInTheDocument();
  });

  test("AC-2: completed row has a View Report link; running/failed rows have none", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportHistoryView />);

    const link = await screen.findByRole("link", { name: /view report/i });
    expect(link).toHaveAttribute("href", "/jobs/job-a/report");
    // only the one completed row yields a report link
    expect(screen.getAllByRole("link", { name: /view report/i })).toHaveLength(1);

    // running row → status hint, no link
    const running = screen.getByText("NDA_draft.docx").closest("tr")!;
    expect(within(running).queryByRole("link", { name: /view report/i })).toBeNull();
    expect(within(running).getByText(/processing/i)).toBeInTheDocument();

    // failed row → no link
    const failed = screen.getByText("vendor_terms.pdf").closest("tr")!;
    expect(within(failed).queryByRole("link", { name: /view report/i })).toBeNull();
  });

  test("parity: renders select-all + per-row checkboxes (screen-12 chrome)", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportHistoryView />);
    await screen.findByText("MSA_AcmeCorp.pdf");
    expect(screen.getByLabelText(/select all rows/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/select row job-a/i)).toBeInTheDocument();
  });

  test("parity: risk filter narrows rows client-side", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportHistoryView />);
    await screen.findByText("MSA_AcmeCorp.pdf");

    fireEvent.change(screen.getByLabelText(/filter by risk/i), { target: { value: "high" } });
    expect(screen.getByText("MSA_AcmeCorp.pdf")).toBeInTheDocument(); // high
    expect(screen.queryByText("NDA_draft.docx")).toBeNull(); // running, no band
    expect(screen.queryByText("vendor_terms.pdf")).toBeNull(); // failed, no band
  });

  test("parity: status filter narrows rows client-side", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportHistoryView />);
    await screen.findByText("MSA_AcmeCorp.pdf");

    fireEvent.change(screen.getByLabelText(/filter by status/i), { target: { value: "failed" } });
    expect(screen.getByText("vendor_terms.pdf")).toBeInTheDocument();
    expect(screen.queryByText("MSA_AcmeCorp.pdf")).toBeNull();
    expect(screen.queryByText("NDA_draft.docx")).toBeNull();
  });

  test("AC-3: Upload New Contract links to /upload", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportHistoryView />);
    const btn = await screen.findByRole("link", { name: /upload new contract/i });
    expect(btn).toHaveAttribute("href", "/upload");
  });

  test("AC-4: filename search filters (case-insensitive); clearing restores", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportHistoryView />);
    await screen.findByText("MSA_AcmeCorp.pdf");

    const box = screen.getByRole("searchbox");
    fireEvent.change(box, { target: { value: "msa" } });
    expect(screen.getByText("MSA_AcmeCorp.pdf")).toBeInTheDocument();
    expect(screen.queryByText("NDA_draft.docx")).toBeNull();
    expect(screen.queryByText("vendor_terms.pdf")).toBeNull();

    fireEvent.change(box, { target: { value: "" } });
    expect(screen.getByText("NDA_draft.docx")).toBeInTheDocument();
    expect(screen.getByText("vendor_terms.pdf")).toBeInTheDocument();
  });

  test("EC-5: search with no matches shows a distinct no-results message", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportHistoryView />);
    await screen.findByText("MSA_AcmeCorp.pdf");

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "zzz-nope" } });
    expect(screen.getByText(/no contracts match/i)).toBeInTheDocument();
    // search still editable
    expect(screen.getByRole("searchbox")).toBeInTheDocument();
  });

  test("AC-5: clicking a sortable header reorders rows", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ jobList: sortableList }));
    render(<ReportHistoryView />);
    await screen.findByText("Zebra_terms.pdf");

    // default: newest-first → Zebra (Jan 30) before Alpha (Jan 29)
    let rows = screen.getAllByRole("row");
    expect(rows[1].textContent).toContain("Zebra_terms.pdf");

    fireEvent.click(screen.getByRole("button", { name: /sort by contract/i }));
    rows = screen.getAllByRole("row");
    expect(rows[1].textContent).toContain("Alpha_terms.pdf");
  });

  test("AC-6: pagination appears past one page and Next advances", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ jobList: manyItems(25) }));
    render(<ReportHistoryView />);
    await screen.findByText("contract_000.pdf");

    // page 1: first 20 present, item 20 not yet
    expect(screen.getByText("contract_019.pdf")).toBeInTheDocument();
    expect(screen.queryByText("contract_020.pdf")).toBeNull();
    expect(screen.getByText(/1\D+20\D+of\D+25/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByText("contract_020.pdf")).toBeInTheDocument();
    expect(screen.getByText("contract_024.pdf")).toBeInTheDocument();
    expect(screen.getByText(/21\D+25\D+of\D+25/)).toBeInTheDocument();
  });

  test("AC-6: a single page shows no pager", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportHistoryView />);
    await screen.findByText("MSA_AcmeCorp.pdf");
    expect(screen.queryByRole("button", { name: /next/i })).toBeNull();
  });

  test("AC-7: empty state with an Upload CTA to /upload", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ jobList: emptyJobListFixture }));
    render(<ReportHistoryView />);
    expect(await screen.findByText(/no contracts yet/i)).toBeInTheDocument();
    const cta = screen.getByRole("link", { name: /upload your first contract/i });
    expect(cta).toHaveAttribute("href", "/upload");
    // not an empty table with headers
    expect(screen.queryByRole("table")).toBeNull();
  });

  test("AC-8: error state with a retry that re-calls getJobs", async () => {
    const client = makeFakeClient({ jobsError: new ApiError("boom", 500) });
    vi.mocked(getApiClient).mockReturnValue(client);
    render(<ReportHistoryView />);

    const retry = await screen.findByRole("button", { name: /try again/i });
    expect(client.getJobs).toHaveBeenCalledTimes(1);
    fireEvent.click(retry);
    await waitFor(() => expect(client.getJobs).toHaveBeenCalledTimes(2));
  });

  test("EC-6: overflow note when total exceeds fetched", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ jobList: { total: 150, items: manyItems(3).items } }),
    );
    render(<ReportHistoryView />);
    expect(await screen.findByText(/showing the most recent 3 of 150/i)).toBeInTheDocument();
  });
});
