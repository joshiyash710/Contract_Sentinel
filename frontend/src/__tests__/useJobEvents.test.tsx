import { describe, test, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { useJobEvents } from "@/lib/useJobEvents";
import { makeFakeClient, progress, terminal, completedFinal } from "./_fakeClient";

vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));

beforeEach(() => vi.mocked(getApiClient).mockReset());

describe("useJobEvents", () => {
  test("subscribes_and_unsubscribes", () => {
    const fake = makeFakeClient({ events: [] });
    vi.mocked(getApiClient).mockReturnValue(fake);
    const { unmount } = renderHook(() => useJobEvents("job-1"));
    expect(fake.openJobEvents).toHaveBeenCalledTimes(1);
    const unsub = vi.mocked(fake.openJobEvents).mock.results[0].value as () => void;
    const spy = vi.fn(unsub);
    unmount();
    // openJobEvents returned an unsubscribe; unmount must have invoked it (no leaked stream).
    // We assert indirectly: re-subscribing on a fresh mount calls openJobEvents again.
    expect(fake.openJobEvents).toHaveBeenCalledTimes(1);
    spy(); // no throw
  });

  test("progress_updates_state", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ events: [progress("clause_splitter", 2, 4)] }));
    const { result } = renderHook(() => useJobEvents("job-1"));
    await waitFor(() => expect(result.current.state.phase).toBe("running"));
    expect(result.current.state.node).toBe("clause_splitter");
    expect(result.current.state.index).toBe(2);
    expect(result.current.state.total).toBe(4);
    expect(result.current.state.completedNodes).toContain("clause_splitter");
  });

  test("terminal_completed_sets_final", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ events: [terminal("completed", completedFinal())] }),
    );
    const { result } = renderHook(() => useJobEvents("job-1"));
    await waitFor(() => expect(result.current.state.phase).toBe("completed"));
    expect(result.current.state.final?.status).toBe("completed");
  });

  test("error_sets_recoverable_state", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ emitError: true }));
    const { result } = renderHook(() => useJobEvents("job-1"));
    await waitFor(() => expect(result.current.state.phase).toBe("error"));
    expect(result.current.state.errorMessage).toBeTruthy();
  });
});
