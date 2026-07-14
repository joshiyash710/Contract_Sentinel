import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { ApiError } from "@/lib/api/client";
import { ReportsView } from "@/components/dashboard/ReportsView";
import { makeFakeClient } from "./_fakeClient";
import { emptyDashboardFixture } from "@/lib/api/fixtures";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));

beforeEach(() => vi.mocked(getApiClient).mockReset());

describe("ReportsView (spec 018 AC-14/15/16)", () => {
  test("renders_real_aggregates", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportsView />);
    expect(await screen.findByText("Risk by Clause Type")).toBeInTheDocument();
    // Total Contracts headline = completed_contracts (4 in fixture), not "339".
    expect(screen.getByText("Total Contracts Analyzed")).toBeInTheDocument();
    expect(screen.queryByText("339")).not.toBeInTheDocument();
    expect(screen.queryByText(/80%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\/100/)).not.toBeInTheDocument();
    // Top risky clause type from fixture (appears in bar/heatmap/top-list — assert presence).
    expect(screen.getAllByText("liability").length).toBeGreaterThan(0);
    // (Stacked-bar series rendering is covered by barchart-stacked.test.tsx.)
  });

  test("empty_state", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ dashboard: emptyDashboardFixture }));
    render(<ReportsView />);
    expect(await screen.findByText(/no contracts analyzed yet/i)).toBeInTheDocument();
  });

  test("error_state_with_retry", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ dashboardError: new ApiError("x", 500) }));
    render(<ReportsView />);
    expect(await screen.findByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});
