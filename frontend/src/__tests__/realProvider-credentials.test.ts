/**
 * AC-18a: every realProvider fetch sets credentials:"include" and the EventSource
 * uses withCredentials:true (spec D15 — cookie must be sent on every call).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { realClient } from "@/lib/api/realProvider";

// ── fetch stub ───────────────────────────────────────────────────────────────

function okResponse(body: unknown = {}): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

// ── EventSource stub ─────────────────────────────────────────────────────────

class MockEventSource {
  static lastOpts: EventSourceInit | undefined;
  url: string;
  withCredentials: boolean;
  onerror: ((e: Event) => void) | null = null;
  constructor(url: string, opts?: EventSourceInit) {
    this.url = url;
    this.withCredentials = opts?.withCredentials ?? false;
    MockEventSource.lastOpts = opts;
  }
  addEventListener() {}
  removeEventListener() {}
  close() {}
}

beforeEach(() => {
  MockEventSource.lastOpts = undefined;
  vi.stubGlobal("EventSource", MockEventSource);
});

describe("realProvider credentials", () => {
  it("submitAnalysis uses credentials:include", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(okResponse({ job_id: "j1", status: "queued", submitted_at: "t" }));
    await realClient.submitAnalysis(new File(["x"], "c.pdf", { type: "application/pdf" }));
    expect(fetchSpy.mock.calls[0][1]).toMatchObject({ credentials: "include" });
    fetchSpy.mockRestore();
  });

  it("getJob uses credentials:include", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        okResponse({
          job_id: "j1", status: "queued", submitted_at: "t",
          completed_nodes: [], report_available: false, mcp_delivery_status: {},
        }),
      );
    await realClient.getJob("j1");
    expect(fetchSpy.mock.calls[0][1]).toMatchObject({ credentials: "include" });
    fetchSpy.mockRestore();
  });

  it("getReport uses credentials:include", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        okResponse({
          document_id: "d", original_filename: "f.pdf", uploaded_at: "t",
          generated_at: "t", ocr_used: false, summary: {
            total_clauses: 0, validated_findings: 0, clean_clauses: 0, high: 0, medium: 0, low: 0,
          }, findings: [], node_timings: {}, error_count: 0,
        }),
      );
    await realClient.getReport("j1");
    expect(fetchSpy.mock.calls[0][1]).toMatchObject({ credentials: "include" });
    fetchSpy.mockRestore();
  });

  it("getJobs uses credentials:include", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(okResponse({ items: [], total: 0 }));
    await realClient.getJobs();
    expect(fetchSpy.mock.calls[0][1]).toMatchObject({ credentials: "include" });
    fetchSpy.mockRestore();
  });

  it("getDashboardMetrics uses credentials:include", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        okResponse({
          total_contracts: 0, completed_contracts: 0,
          risk_distribution: { high: 0, medium: 0, low: 0 },
          portfolio_health_pct: 100, portfolio_health_band: "healthy",
          usage_timeline: [], risk_by_clause_type: [],
          clause_risk_heatmap: { rows: [], cols: [], cells: [] },
          top_risky_clause_types: [],
        }),
      );
    await realClient.getDashboardMetrics();
    expect(fetchSpy.mock.calls[0][1]).toMatchObject({ credentials: "include" });
    fetchSpy.mockRestore();
  });

  it("health uses credentials:include", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(okResponse({ status: "ok" }));
    await realClient.health();
    expect(fetchSpy.mock.calls[0][1]).toMatchObject({ credentials: "include" });
    fetchSpy.mockRestore();
  });

  it("signup uses credentials:include", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(okResponse({ user: { id: "u1", email: "a@b.com" } }));
    await realClient.signup("a@b.com", "password123", "A B");
    expect(fetchSpy.mock.calls[0][1]).toMatchObject({ credentials: "include" });
    fetchSpy.mockRestore();
  });

  it("login uses credentials:include", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(okResponse({ user: { id: "u1", email: "a@b.com" } }));
    await realClient.login("a@b.com", "password123");
    expect(fetchSpy.mock.calls[0][1]).toMatchObject({ credentials: "include" });
    fetchSpy.mockRestore();
  });

  it("logout uses credentials:include", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(okResponse({ ok: true }));
    await realClient.logout();
    expect(fetchSpy.mock.calls[0][1]).toMatchObject({ credentials: "include" });
    fetchSpy.mockRestore();
  });

  it("me uses credentials:include", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(okResponse({ user: { id: "u1", email: "a@b.com" } }));
    await realClient.me();
    expect(fetchSpy.mock.calls[0][1]).toMatchObject({ credentials: "include" });
    fetchSpy.mockRestore();
  });

  it("openJobEvents uses withCredentials:true on EventSource", () => {
    const unsub = realClient.openJobEvents("j1", {});
    expect(MockEventSource.lastOpts?.withCredentials).toBe(true);
    unsub();
  });
});
