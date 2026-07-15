/**
 * Feature 019 (AC-B6): with per-user isolation, a brand-new account genuinely starts empty,
 * so the dashboard and reports must render a polished "upload your first contract" empty
 * state (not demo numbers) when the client returns zero jobs.
 */
import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { DashboardView } from "@/components/dashboard/DashboardView";
import { ReportsView } from "@/components/dashboard/ReportsView";
import { makeFakeClient } from "./_fakeClient";
import { emptyDashboardFixture, emptyJobListFixture } from "@/lib/api/fixtures";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));

beforeEach(() => vi.mocked(getApiClient).mockReset());

describe("AC-B6: empty workspace states", () => {
  test("dashboard shows the upload-first-contract empty state", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ dashboard: emptyDashboardFixture, jobList: emptyJobListFixture }),
    );
    render(<DashboardView />);
    expect(await screen.findByText(/no contracts analyzed yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /upload a contract/i })).toHaveAttribute(
      "href",
      "/upload",
    );
    // No fabricated/demo numbers leak into the empty state.
    expect(screen.queryByText(/\/100/)).not.toBeInTheDocument();
  });

  test("reports shows the empty state", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ dashboard: emptyDashboardFixture, jobList: emptyJobListFixture }),
    );
    render(<ReportsView />);
    expect(await screen.findByText(/no contracts analyzed yet/i)).toBeInTheDocument();
  });
});
