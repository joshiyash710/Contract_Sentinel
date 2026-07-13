import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { ProcessingView } from "@/components/processing/ProcessingView";
import { makeFakeClient, runningStatus, queuedStatus, completedFinal } from "./_fakeClient";

const push = vi.fn();
const replace = vi.fn(); // 017: clean completions call router.replace (auto-redirect)
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace }) }));
vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));
// 017: neutralize the auto-redirect delay so a clean completion doesn't navigate mid-test.
vi.mock("@/lib/reportConstants", () => ({ REPORT_REDIRECT_DELAY_MS: 100000 }));

beforeEach(() => {
  push.mockReset();
  replace.mockReset();
  vi.mocked(getApiClient).mockReset();
});

describe("ProcessingView (polling — spec AC-9..AC-15, EC-1/2/6/8)", () => {
  test("renders_connecting_before_first_progress", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ statuses: [queuedStatus()] }));
    render(<ProcessingView jobId="job-1" />);
    expect(await screen.findByText(/starting analysis/i)).toBeInTheDocument();
  });

  test("renders_progress", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ statuses: [runningStatus("clause_splitter", ["ingest_agent", "clause_splitter"])] }),
    );
    render(<ProcessingView jobId="job-1" />);
    expect(await screen.findByText(/breaking the document into clauses/i)).toBeInTheDocument();
    expect(screen.getByText(/step 2 of 7/i)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "29");
  });

  test("unknown_node_generic_label", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ statuses: [runningStatus("nope")] }));
    render(<ProcessingView jobId="job-1" />);
    expect(await screen.findByText("Analyzing…")).toBeInTheDocument();
  });

  // 017 (spec D1): a clean completion now auto-redirects to the report page instead of
  // showing inline "View report"/"View JSON" links. The redirect assertion lives in
  // processing-redirect.test.tsx; here we assert the resting "Analysis complete ✓" flourish
  // (the delay is mocked large above so no navigation happens during this test).
  test("completed_shows_complete_flourish_not_inline_links", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ statuses: [completedFinal({ report_available: true })] }),
    );
    render(<ProcessingView jobId="job-1" />);
    expect(await screen.findByText(/analysis complete/i)).toBeInTheDocument();
    expect(screen.getByText(/taking you to your report/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /view report/i })).toBeNull();
    expect(screen.queryByRole("link", { name: /view json/i })).toBeNull();
  });

  test("ingest_error_soft_state", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({
        statuses: [completedFinal({ report_available: false, error: { kind: "ingest_error", message: "corrupt pdf" } })],
      }),
    );
    render(<ProcessingView jobId="job-1" />);
    expect(await screen.findByText(/corrupt pdf/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /view report/i })).toBeNull();
  });

  test("failed_shows_retry", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ statuses: [completedFinal({ status: "failed", error: { kind: "runner_exception", message: "boom" } })] }),
    );
    render(<ProcessingView jobId="job-1" />);
    const retry = await screen.findByRole("button", { name: /retry/i });
    fireEvent.click(retry);
    expect(push).toHaveBeenCalledWith("/upload");
  });

  test("already_finished_lands_terminal", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ statuses: [completedFinal()] }));
    render(<ProcessingView jobId="job-1" />);
    expect(await screen.findByText(/analysis complete/i)).toBeInTheDocument();
  });

  test("error_phase_refresh_reconnects", async () => {
    const fake = makeFakeClient({ getJobError: new Error("404") });
    vi.mocked(getApiClient).mockReturnValue(fake);
    render(<ProcessingView jobId="job-1" />);
    const refresh = await screen.findByRole("button", { name: /refresh/i });
    const before = vi.mocked(fake.getJob).mock.calls.length;
    fireEvent.click(refresh);
    await waitFor(() => expect(vi.mocked(fake.getJob).mock.calls.length).toBeGreaterThan(before));
  });
});
