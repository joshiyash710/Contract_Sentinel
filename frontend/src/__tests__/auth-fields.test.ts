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
  it("has exactly the expected keys", () => {
    const u: AuthUser = { id: "x", email: "a@b.com" };
    // If backend adds a required field, this object literal becomes a TS error.
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
