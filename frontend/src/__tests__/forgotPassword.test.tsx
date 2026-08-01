/**
 * Feature 034 — /forgot-password page: posts the email via the provider seam and shows the SAME
 * generic confirmation regardless of the outcome (never discloses account existence).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ApiError } from "@/lib/api/client";
import { makeFakeClient } from "./_fakeClient";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));

let fakeClient = makeFakeClient();
vi.mock("@/lib/api/provider", () => ({ getApiClient: () => fakeClient }));

import ForgotPasswordPage from "@/app/forgot-password/page";

beforeEach(() => {
  fakeClient = makeFakeClient();
});

function submitEmail(value = "user@example.com") {
  render(<ForgotPasswordPage />);
  fireEvent.change(screen.getByLabelText(/email/i), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));
}

describe("/forgot-password", () => {
  it("posts the email and shows the generic confirmation", async () => {
    submitEmail("user@example.com");
    await waitFor(() =>
      expect(fakeClient.requestPasswordReset).toHaveBeenCalledWith("user@example.com"),
    );
    expect(await screen.findByText(/check your email/i)).toBeInTheDocument();
  });

  it("shows the SAME confirmation even when the request rejects (no existence signal)", async () => {
    fakeClient = makeFakeClient({ requestPasswordResetError: new ApiError("boom", 500) });
    submitEmail("ghost@nowhere.test");
    expect(await screen.findByText(/check your email/i)).toBeInTheDocument();
  });
});
