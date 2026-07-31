/**
 * Feature 032 (W2, AC-19): the real provider redirects to /login when a previously-authenticated
 * session goes 401 (idle/absolute/epoch expiry), but NOT on the unauthenticated bootstrap probe.
 * Also covers the logoutAll wiring.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

// Hard-navigation spy (mirrors authView.test): the provider uses window.location.assign.
const assignMock = vi.fn();
Object.defineProperty(window, "location", {
  configurable: true,
  value: { assign: assignMock, href: "http://localhost/dashboard" },
});

import { realClient } from "@/lib/api/realProvider";

function res(status: number, body: unknown = {}): Response {
  return new Response(JSON.stringify(body), { status });
}

beforeEach(() => {
  assignMock.mockClear();
});

describe("session expiry redirect", () => {
  it("does NOT redirect on a bootstrap 401 (never authenticated → no loop)", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(res(401));
    await expect(realClient.me()).rejects.toBeTruthy();
    expect(assignMock).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("redirects to /login on a 401 AFTER a successful login", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockResolvedValueOnce(res(200, { user: { id: "u1", email: "a@b.com" } })); // login
    await realClient.login("a@b.com", "pw123456");
    fetchSpy.mockResolvedValueOnce(res(401)); // a later authenticated call → session expired
    await expect(realClient.getJobs()).rejects.toBeTruthy();
    expect(assignMock).toHaveBeenCalledWith("/login");
    fetchSpy.mockRestore();
  });

  it("logoutAll POSTs to /api/auth/logout-all with credentials", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(res(200, { ok: true }));
    await realClient.logoutAll();
    expect(String(fetchSpy.mock.calls[0][0])).toContain("/api/auth/logout-all");
    expect(fetchSpy.mock.calls[0][1]).toMatchObject({ method: "POST", credentials: "include" });
    fetchSpy.mockRestore();
  });
});
