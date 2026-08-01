/**
 * Feature 034 — /reset page: reads ?token=, posts token+new password, redirects to /login?reset=1 on
 * success, and shows a generic error on a 400/invalid token.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ApiError } from "@/lib/api/client";
import { makeFakeClient } from "./_fakeClient";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams("token=RAWTOKEN"),
}));

let fakeClient = makeFakeClient();
vi.mock("@/lib/api/provider", () => ({ getApiClient: () => fakeClient }));

import ResetPasswordPage from "@/app/reset/page";

beforeEach(() => {
  fakeClient = makeFakeClient();
  replaceMock.mockClear();
});

function fillAndSubmit(pw = "NewPassw0rd!", confirm = "NewPassw0rd!") {
  render(<ResetPasswordPage />);
  fireEvent.change(screen.getByLabelText("New password"), { target: { value: pw } });
  fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: confirm } });
  fireEvent.click(screen.getByRole("button", { name: /reset password/i }));
}

describe("/reset", () => {
  it("posts the token + new password and redirects on success", async () => {
    fillAndSubmit();
    await waitFor(() =>
      expect(fakeClient.resetPassword).toHaveBeenCalledWith("RAWTOKEN", "NewPassw0rd!"),
    );
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/login?reset=1"));
  });

  it("shows a generic error on an invalid/expired token (400)", async () => {
    fakeClient = makeFakeClient({ resetPasswordError: new ApiError("Invalid or expired reset link.", 400) });
    fillAndSubmit();
    expect(await screen.findByText(/invalid or has expired/i)).toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("rejects mismatched passwords client-side without calling the API", async () => {
    fillAndSubmit("NewPassw0rd!", "different");
    expect(await screen.findByText(/do not match/i)).toBeInTheDocument();
    expect(fakeClient.resetPassword).not.toHaveBeenCalled();
  });
});
