import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { getApiClient } from "@/lib/api/provider";
import { mockClient } from "@/lib/api/mockProvider";
import { realClient } from "@/lib/api/realProvider";
import { ApiError } from "@/lib/api/client";
import { JOB_STATES, RISK_LEVELS, DELIVERY_STATES } from "@/lib/api/types";

const JOBSTATE = ["queued", "running", "completed", "failed"];
const RISK = ["low", "medium", "high"];
const DELIVERY = ["pending", "success", "failed"];

describe("api seam", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  test("enum_mirrors_exact", () => {
    expect([...JOB_STATES].sort()).toEqual([...JOBSTATE].sort());
    expect([...RISK_LEVELS].sort()).toEqual([...RISK].sort());
    expect([...DELIVERY_STATES].sort()).toEqual([...DELIVERY].sort());
  });

  test("client_exposes_five_endpoints", () => {
    ["submitAnalysis", "getJob", "openJobEvents", "getReportUrl", "health"].forEach((m) =>
      expect(typeof (mockClient as unknown as Record<string, unknown>)[m]).toBe("function"),
    );
  });

  test("mock_provider_no_network", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    await mockClient.getJob("job-1");
    await mockClient.health();
    await mockClient.submitAnalysis(new File(["x"], "c.pdf"));
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("single_provider_switch", () => {
    vi.stubEnv("NEXT_PUBLIC_API_PROVIDER", "mock");
    expect(getApiClient()).toBe(mockClient);
    vi.stubEnv("NEXT_PUBLIC_API_PROVIDER", "real");
    expect(getApiClient()).toBe(realClient);
  });

  test("sse_named_events_and_terminal", async () => {
    const events: string[] = [];
    let terminalFinal: unknown = null;
    const stop = mockClient.openJobEvents("job-1", {
      onProgress: (e) => events.push(e.event),
      onTerminal: (e) => {
        terminalFinal = e.final;
      },
    });
    await vi.waitFor(() => expect(terminalFinal).not.toBeNull());
    expect(events).toContain("progress");
    expect((terminalFinal as { status: string }).status).toBe("completed");
    stop();
  });

  test("real_provider_hits_base_url", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_PROVIDER", "real");
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
    await realClient.health();
    expect(fetchSpy).toHaveBeenCalledWith("/api/health", expect.objectContaining({ credentials: "include" }));
  });

  test("backend_unreachable_typed_error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("ECONNREFUSED"));
    await expect(realClient.getJob("job-x")).rejects.toBeInstanceOf(ApiError);
  });

  test("get_report_url_shape", () => {
    expect(mockClient.getReportUrl("job-9", "md")).toBe("/api/jobs/job-9/report?format=md");
  });
});
