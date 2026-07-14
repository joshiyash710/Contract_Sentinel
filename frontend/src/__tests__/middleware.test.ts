/**
 * Unit tests for the Next.js middleware gate (spec AC-16 / AC-17 / plan §4.2).
 * Tests the redirect logic as a plain function — no jsdom/Next server needed.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

// We test the handler exported from middleware.ts directly.
// NextRequest / NextResponse are mocked below so the test runs in jsdom without
// a real Next.js server (the middleware runtime is not jsdom-compatible, so we
// test it as a plain TypeScript function).

// ── Minimal NextRequest / NextResponse stubs ─────────────────────────────────

function makeMockRequest(pathname: string, hasCookie: boolean, provider = "real"): Request {
  const url = new URL(`http://localhost:3000${pathname}`);
  const headers = new Headers();
  headers.set("x-pathname", pathname);
  const cookies: Record<string, string> = {};
  if (hasCookie) cookies["cs_session"] = "tok";
  // Minimal stub — the middleware reads .cookies.get() and .nextUrl.pathname
  return {
    url: url.toString(),
    nextUrl: { pathname },
    cookies: { get: (name: string) => (cookies[name] ? { value: cookies[name] } : undefined) },
    headers,
    // environment variable used to skip the gate in mock mode
    _provider: provider,
  } as unknown as Request;
}

// ── Import the handler under test ────────────────────────────────────────────

// We isolate middleware from the Next runtime by importing only the handler
// function. The middleware file must export a named `middlewareHandler` (or
// default-export the function), which we test directly.

describe("middleware redirect logic", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("AC-16: protected path + no cookie → redirect /login", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_PROVIDER", "real");
    const { middlewareHandler } = await import("@/middleware");
    const req = makeMockRequest("/dashboard", false);
    const result = middlewareHandler(req as unknown as Parameters<typeof middlewareHandler>[0]);
    expect(result).toBeDefined();
    expect(result!.status).toBe(307);
    expect(result!.headers.get("location")).toMatch(/\/login/);
  });

  it("AC-17: /login + cookie → redirect /dashboard", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_PROVIDER", "real");
    const { middlewareHandler } = await import("@/middleware");
    const req = makeMockRequest("/login", true);
    const result = middlewareHandler(req as unknown as Parameters<typeof middlewareHandler>[0]);
    expect(result).toBeDefined();
    expect(result!.status).toBe(307);
    expect(result!.headers.get("location")).toMatch(/\/dashboard/);
  });

  it("AC-17: / + cookie → redirect /dashboard", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_PROVIDER", "real");
    const { middlewareHandler } = await import("@/middleware");
    const req = makeMockRequest("/", true);
    const result = middlewareHandler(req as unknown as Parameters<typeof middlewareHandler>[0]);
    expect(result).toBeDefined();
    expect(result!.status).toBe(307);
    expect(result!.headers.get("location")).toMatch(/\/dashboard/);
  });

  it("public path + no cookie → next (pass-through)", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_PROVIDER", "real");
    const { middlewareHandler } = await import("@/middleware");
    const req = makeMockRequest("/login", false);
    const result = middlewareHandler(req as unknown as Parameters<typeof middlewareHandler>[0]);
    // pass-through returns undefined or a non-redirect response
    expect(result === undefined || (result.status !== 307 && result.status !== 308)).toBe(true);
  });

  it("mock provider → always next (no gate)", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_PROVIDER", "mock");
    const { middlewareHandler } = await import("@/middleware");
    const req = makeMockRequest("/dashboard", false);
    const result = middlewareHandler(req as unknown as Parameters<typeof middlewareHandler>[0]);
    // pass-through: no redirect
    expect(result === undefined || (result.status !== 307 && result.status !== 308)).toBe(true);
  });
});
