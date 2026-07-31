/**
 * Feature 032 (AC-19): useJobStatus treats a 401 as terminal-for-session and STOPS polling
 * (the provider already redirects to /login), instead of counting it as a transient blip.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { ApiError } from "@/lib/api/client";

const getJob = vi.fn();
vi.mock("@/lib/api/provider", () => ({ getApiClient: () => ({ getJob }) }));

import { useJobStatus, POLL_INTERVAL_MS } from "@/lib/useJobStatus";

describe("useJobStatus 401 stops polling", () => {
  beforeEach(() => {
    getJob.mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not reschedule a poll after a 401", async () => {
    getJob.mockRejectedValue(new ApiError("unauthorized", 401));
    renderHook(() => useJobStatus("job-1"));

    await vi.advanceTimersByTimeAsync(0); // flush the first (mount) tick
    expect(getJob).toHaveBeenCalledTimes(1);

    // Well past several poll intervals — a 401 must NOT schedule another poll.
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3);
    expect(getJob).toHaveBeenCalledTimes(1);
  });
});
