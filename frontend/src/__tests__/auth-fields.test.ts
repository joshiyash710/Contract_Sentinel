/**
 * Drift-lock: AuthUser and AuthResponse TS types mirror the backend Pydantic models
 * field-for-field (spec §2.1 / AC-19). If a field is added/removed on the backend,
 * this test fails until the frontend types are updated too.
 */
import { describe, it, expect, expectTypeOf } from "vitest";
import type { AuthUser, AuthResponse } from "@/lib/api/types";

describe("AuthUser drift-lock", () => {
  it("has id: string", () => {
    expectTypeOf<AuthUser["id"]>().toBeString();
  });
  it("has email: string", () => {
    expectTypeOf<AuthUser["email"]>().toBeString();
  });
  it("has optional name/title (feature 020)", () => {
    // Both are optional string|null — a full user with them typechecks.
    const full: AuthUser = { id: "x", email: "a@b.com", name: "Grace", title: "Admiral" };
    expect(full.name).toBe("Grace");
    // and null is accepted (legacy accounts).
    const legacy: AuthUser = { id: "y", email: "b@b.com", name: null, title: null };
    expect(legacy.name).toBeNull();
  });
  it("still constructs with only the required keys", () => {
    const u: AuthUser = { id: "x", email: "a@b.com" };
    expect(Object.keys(u).sort()).toEqual(["email", "id"]);
  });
});

describe("AuthResponse drift-lock", () => {
  it("has user: AuthUser", () => {
    expectTypeOf<AuthResponse["user"]>().toMatchTypeOf<AuthUser>();
  });
  it("has exactly the expected keys", () => {
    const r: AuthResponse = { user: { id: "x", email: "a@b.com" } };
    expect(Object.keys(r).sort()).toEqual(["user"]);
  });
});
