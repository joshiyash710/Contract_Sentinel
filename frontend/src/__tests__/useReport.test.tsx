import { describe, test, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { ApiError } from "@/lib/api/client";
import { useReport } from "@/lib/useReport";
import { makeFakeClient, completedFinal, runningStatus } from "./_fakeClient";

vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));

beforeEach(() => {
  vi.mocked(getApiClient).mockReset();
});

describe("useReport (spec 017 D7 / AC-14, EC-1/2/3)", () => {
  test("loads_report", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    const { result } = renderHook(() => useReport("job-1"));
    await waitFor(() => expect(result.current.state.phase).toBe("loaded"));
    expect(result.current.state.report?.original_filename).toBeTruthy();
  });

  test("409_redirects", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ getReportError: new ApiError("not ready", 409) }),
    );
    const { result } = renderHook(() => useReport("job-1"));
    await waitFor(() => expect(result.current.state.phase).toBe("redirecting"));
  });

  test("404_unknown_job", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({
        getReportError: new ApiError("missing", 404),
        getJobError: new ApiError("no job", 404),
      }),
    );
    const { result } = renderHook(() => useReport("job-1"));
    await waitFor(() => expect(result.current.state.phase).toBe("not_found"));
  });

  test("404_completed_job_artifact_unavailable", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({
        getReportError: new ApiError("missing file", 404),
        statuses: [completedFinal({ status: "completed" })],
      }),
    );
    const { result } = renderHook(() => useReport("job-1"));
    await waitFor(() => expect(result.current.state.phase).toBe("artifact_unavailable"));
  });

  test("404_running_job_redirects", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({
        getReportError: new ApiError("missing", 404),
        statuses: [runningStatus("clause_splitter")],
      }),
    );
    const { result } = renderHook(() => useReport("job-1"));
    await waitFor(() => expect(result.current.state.phase).toBe("redirecting"));
  });

  test("network_error_then_retry", async () => {
    const fake = makeFakeClient({ getReportError: new ApiError("network") });
    vi.mocked(getApiClient).mockReturnValue(fake);
    const { result } = renderHook(() => useReport("job-1"));
    await waitFor(() => expect(result.current.state.phase).toBe("error"));

    // Flip the fake to succeed, then retry() should re-fetch and load.
    (fake.getReport as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ...(await makeFakeClient({}).getReport("job-1")),
    });
    result.current.retry();
    await waitFor(() => expect(result.current.state.phase).toBe("loaded"));
  });
});
