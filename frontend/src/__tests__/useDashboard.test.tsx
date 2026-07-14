import { describe, test, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { ApiError } from "@/lib/api/client";
import { useDashboard } from "@/lib/useDashboard";
import { makeFakeClient } from "./_fakeClient";
import { emptyDashboardFixture } from "@/lib/api/fixtures";

vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));

beforeEach(() => vi.mocked(getApiClient).mockReset());

describe("useDashboard (spec 018 D11 / AC-16)", () => {
  test("loads_metrics", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.state.phase).toBe("loaded"));
    expect(result.current.state.data?.total_contracts).toBeGreaterThan(0);
  });

  test("empty_when_no_contracts", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ dashboard: emptyDashboardFixture }));
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.state.phase).toBe("empty"));
  });

  test("error_then_retry", async () => {
    const fake = makeFakeClient({ dashboardError: new ApiError("500", 500) });
    vi.mocked(getApiClient).mockReturnValue(fake);
    const { result } = renderHook(() => useDashboard());
    await waitFor(() => expect(result.current.state.phase).toBe("error"));

    (fake.getDashboardMetrics as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      await makeFakeClient({}).getDashboardMetrics(),
    );
    result.current.retry();
    await waitFor(() => expect(result.current.state.phase).toBe("loaded"));
  });
});
