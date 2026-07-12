import { describe, test, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { useJobStatus } from "@/lib/useJobStatus";
import { makeFakeClient, runningStatus, queuedStatus, completedFinal } from "./_fakeClient";

vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));

beforeEach(() => vi.mocked(getApiClient).mockReset());

describe("useJobStatus (polling — spec D7)", () => {
  test("polls_getJob_on_mount", async () => {
    const fake = makeFakeClient({ statuses: [completedFinal()] });
    vi.mocked(getApiClient).mockReturnValue(fake);
    renderHook(() => useJobStatus("job-1"));
    await waitFor(() => expect(fake.getJob).toHaveBeenCalled());
  });

  test("running_maps_node_and_index", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ statuses: [runningStatus("clause_splitter", ["ingest_agent", "clause_splitter"])] }),
    );
    const { result } = renderHook(() => useJobStatus("job-1"));
    await waitFor(() => expect(result.current.state.phase).toBe("running"));
    expect(result.current.state.node).toBe("clause_splitter");
    expect(result.current.state.index).toBe(2); // node→index map
    expect(result.current.state.total).toBe(7);
    expect(result.current.state.completedNodes).toContain("ingest_agent");
  });

  test("queued_is_connecting", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ statuses: [queuedStatus()] }));
    const { result } = renderHook(() => useJobStatus("job-1"));
    // stays connecting on a queued status (keeps polling)
    await waitFor(() => expect(getApiClient().getJob).toHaveBeenCalled());
    expect(result.current.state.phase).toBe("connecting");
  });

  test("completed_sets_final", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ statuses: [completedFinal()] }));
    const { result } = renderHook(() => useJobStatus("job-1"));
    await waitFor(() => expect(result.current.state.phase).toBe("completed"));
    expect(result.current.state.final?.status).toBe("completed");
  });

  test("getJob_error_sets_recoverable_state", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ getJobError: new Error("404") }));
    const { result } = renderHook(() => useJobStatus("job-1"));
    await waitFor(() => expect(result.current.state.phase).toBe("error"));
    expect(result.current.state.errorMessage).toBeTruthy();
  });
});
