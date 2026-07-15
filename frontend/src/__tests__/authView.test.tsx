/**
 * Tests for AuthView (feature 014) — login/signup submit + error mapping.
 * AC-12 (disabled buttons/inert link), AC-13 (login flow), AC-14 (signup flow).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { ApiError } from "@/lib/api/client";
import { makeFakeClient } from "./_fakeClient";
import { authUserFixture } from "@/lib/api/fixtures";

// ── Router mock ───────────────────────────────────────────────────────────────
const mockReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  usePathname: () => "/login",
}));

// ── ApiClient mock (getApiClient returns the fake) ────────────────────────────
let fakeClient = makeFakeClient();
vi.mock("@/lib/api/provider", () => ({
  getApiClient: () => fakeClient,
}));

import { AuthView } from "@/components/auth/AuthView";

function renderAuth(tab: "login" | "signup" = "login") {
  return render(<AuthView defaultTab={tab} />);
}

beforeEach(() => {
  fakeClient = makeFakeClient();
  mockReplace.mockClear();
});

// ── AC-12: Google/Microsoft disabled; Forgot-Password inert ──────────────────

describe("AC-12: SSO buttons disabled and Forgot-Password inert", () => {
  it("Google button is disabled", () => {
    renderAuth();
    const google = screen.getByRole("button", { name: /google/i });
    expect(google).toBeDisabled();
  });

  it("Microsoft button is disabled", () => {
    renderAuth();
    const ms = screen.getByRole("button", { name: /microsoft/i });
    expect(ms).toBeDisabled();
  });

  it("Forgot Password link does not navigate", async () => {
    renderAuth("login");
    const fp = screen.getByText(/forgot password/i);
    // inert — no href that causes navigation; clicking does not call router
    fireEvent.click(fp);
    expect(mockReplace).not.toHaveBeenCalled();
  });
});

// ── AC-B3: underline tabs switch the active form ─────────────────────────────

describe("AC-B3: tabs switch the active form", () => {
  it("clicking the Sign Up tab makes submit call signup()", async () => {
    fakeClient = makeFakeClient({ authUser: authUserFixture });
    renderAuth("login");

    // Start on login; switch to Sign Up via the tab.
    fireEvent.click(screen.getByRole("tab", { name: /sign up/i }));

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "new@b.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password123" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    });

    await waitFor(() => expect(fakeClient.signup).toHaveBeenCalledWith("new@b.com", "password123"));
    expect(fakeClient.login).not.toHaveBeenCalled();
  });
});

// ── AC-13: Login tab submit ───────────────────────────────────────────────────

describe("AC-13: Login tab", () => {
  it("success → calls login() and navigates to /dashboard", async () => {
    fakeClient = makeFakeClient({ authUser: authUserFixture });
    renderAuth("login");

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password123" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    });

    await waitFor(() => expect(fakeClient.login).toHaveBeenCalledWith("a@b.com", "password123"));
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/dashboard"));
  });

  it("401 → shows inline error, no navigation", async () => {
    fakeClient = makeFakeClient({ authError: new ApiError("bad creds", 401) });
    renderAuth("login");

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    });

    await waitFor(() => expect(screen.getByText(/invalid email or password/i)).toBeTruthy());
    expect(mockReplace).not.toHaveBeenCalled();
  });
});

// ── AC-14: Sign-Up tab submit ─────────────────────────────────────────────────

describe("AC-14: Sign-Up tab", () => {
  function goToSignup() {
    renderAuth("signup");
  }

  it("success → calls signup() and navigates to /dashboard", async () => {
    fakeClient = makeFakeClient({ authUser: authUserFixture });
    goToSignup();

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "new@b.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password123" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    });

    await waitFor(() => expect(fakeClient.signup).toHaveBeenCalledWith("new@b.com", "password123"));
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/dashboard"));
  });

  it("409 → shows 'account already exists' error", async () => {
    fakeClient = makeFakeClient({ authError: new ApiError("dup", 409) });
    goToSignup();

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "dup@b.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password123" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    });

    await waitFor(() => expect(screen.getByText(/already exists/i)).toBeTruthy());
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("422 → shows password policy error", async () => {
    fakeClient = makeFakeClient({ authError: new ApiError("weak pw", 422) });
    goToSignup();

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "short" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    });

    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(mockReplace).not.toHaveBeenCalled();
  });
});
