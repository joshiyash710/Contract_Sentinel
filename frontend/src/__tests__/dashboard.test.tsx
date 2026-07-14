import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { ApiError } from "@/lib/api/client";
import { DashboardView } from "@/components/dashboard/DashboardView";
import { makeFakeClient } from "./_fakeClient";
import { emptyDashboardFixture, emptyJobListFixture } from "@/lib/api/fixtures";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));

beforeEach(() => vi.mocked(getApiClient).mockReset());

describe("DashboardView (spec 018 AC-13/15/16/17)", () => {
  test("renders_real_metrics_and_feed", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<DashboardView />);
    expect(await screen.findByText("AI Command Center")).toBeInTheDocument();
    // Activity feed shows a real filename from the job list fixture.
    expect(await screen.findByText("MSA_AcmeCorp.pdf")).toBeInTheDocument();
    // Derived health, not a fabricated score — no "/100", no "78".
    expect(screen.queryByText(/\/100/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\b78\b/)).not.toBeInTheDocument();
  });

  test("completed_feed_row_links_to_report", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<DashboardView />);
    const link = await screen.findByRole("link", { name: /MSA_AcmeCorp\.pdf/i });
    expect(link).toHaveAttribute("href", "/jobs/job-a/report"); // AC-17
  });

  test("empty_state_when_no_contracts", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ dashboard: emptyDashboardFixture, jobList: emptyJobListFixture }),
    );
    render(<DashboardView />);
    expect(await screen.findByText(/no contracts analyzed yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /upload a contract/i })).toHaveAttribute("href", "/upload");
  });

  test("error_state_with_retry", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ dashboardError: new ApiError("x", 500) }));
    render(<DashboardView />);
    expect(await screen.findByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});
