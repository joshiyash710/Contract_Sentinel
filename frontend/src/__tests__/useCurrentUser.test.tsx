/**
 * Feature 020 (AC-8): useCurrentUser resolves the logged-in person, falls back to the email
 * local part when the name is null (legacy accounts), and never throws on an unauthenticated
 * me() (401).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { ApiError } from "@/lib/api/client";
import { makeFakeClient } from "./_fakeClient";
import { useCurrentUser, clearCurrentUser, displayNameFor } from "@/lib/useCurrentUser";

vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));

beforeEach(() => {
  vi.mocked(getApiClient).mockReset();
  clearCurrentUser(); // reset the module cache between tests
});

describe("useCurrentUser", () => {
  it("returns the real name + title when me() has one", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ authUser: { id: "u", email: "a@b.com", name: "Grace Hopper", title: "Admiral" } }),
    );
    const { result } = renderHook(() => useCurrentUser());
    await waitFor(() => expect(result.current.displayName).toBe("Grace Hopper"));
    expect(result.current.title).toBe("Admiral");
  });

  it("falls back to the email local part when name is null", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ authUser: { id: "u", email: "smoke@example.com", name: null, title: null } }),
    );
    const { result } = renderHook(() => useCurrentUser());
    await waitFor(() => expect(result.current.displayName).toBe("smoke"));
  });

  it("yields no user and does not throw on a 401", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ authError: new ApiError("unauthorized", 401) }),
    );
    const { result } = renderHook(() => useCurrentUser());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user).toBeNull();
    expect(result.current.displayName).toBe("there");
  });
});

describe("displayNameFor (pure)", () => {
  it("prefers name, then email local part, then a neutral fallback", () => {
    expect(displayNameFor({ id: "1", email: "x@y.com", name: "Ada" })).toBe("Ada");
    expect(displayNameFor({ id: "1", email: "dev@y.com", name: null })).toBe("dev");
    expect(displayNameFor(null)).toBe("there");
  });
});
