import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { ProcessingView } from "@/components/processing/ProcessingView";
import { makeFakeClient, completedFinal } from "./_fakeClient";

const push = vi.fn();
const replace = vi.fn();
// Router mock MUST expose BOTH push and replace (review B1) — the redirect uses replace,
// the failed-Retry path uses push.
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace }) }));
vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));
// Neutralize the redirect delay (review B3) — real timers + delay 0 avoids the
// fake-timer/microtask/RTL-waitFor deadlock. The poll resolves via a microtask; with the
// delay at 0 the redirect fires on the next macrotask and waitFor observes it.
vi.mock("@/lib/reportConstants", () => ({ REPORT_REDIRECT_DELAY_MS: 0 }));

beforeEach(() => {
  push.mockReset();
  replace.mockReset();
  vi.mocked(getApiClient).mockReset();
});

describe("ProcessingView auto-redirect (spec 017 AC-12/AC-13, EC-9, INV-1/INV-3)", () => {
  test("completed_auto_redirects", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ statuses: [completedFinal({ report_available: true })] }),
    );
    render(<ProcessingView jobId="job-1" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/jobs/job-1/report"));
    // The old inline "View report" link is not the resting state.
    expect(screen.queryByRole("link", { name: /view report/i })).not.toBeInTheDocument();
  });

  test("completed_redirect_uses_replace_not_push", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ statuses: [completedFinal({ report_available: true })] }),
    );
    render(<ProcessingView jobId="job-1" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/jobs/job-1/report"));
    // Back must not land on the finished processing screen (EC-9) — never push the report URL.
    expect(push).not.toHaveBeenCalledWith("/jobs/job-1/report");
  });

  test("completed_no_report_stays_inline", async () => {
    // Synthetic INV-1-violating guard state (a clean completion always has report_available).
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ statuses: [completedFinal({ report_available: false })] }),
    );
    render(<ProcessingView jobId="job-1" />);
    await screen.findByText(/analysis complete/i);
    // Give any pending microtask/timer a chance, then assert no redirect.
    await new Promise((r) => setTimeout(r, 5));
    expect(replace).not.toHaveBeenCalled();
  });

  test("completed_with_issue_no_redirect", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({
        statuses: [
          completedFinal({
            report_available: true,
            error: { kind: "ingest_error", message: "bad pdf" },
          }),
        ],
      }),
    );
    render(<ProcessingView jobId="job-1" />);
    expect(await screen.findByText(/finished with an issue/i)).toBeInTheDocument();
    expect(screen.getByText(/bad pdf/i)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 5));
    expect(replace).not.toHaveBeenCalled();
  });

  test("failed_unchanged", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ statuses: [completedFinal({ status: "failed" })] }),
    );
    render(<ProcessingView jobId="job-1" />);
    const retry = await screen.findByRole("button", { name: /retry/i });
    retry.click();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/upload"));
    expect(replace).not.toHaveBeenCalled();
  });
});
