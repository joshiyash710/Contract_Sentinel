import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { ApiError } from "@/lib/api/client";
import { AccountSettingsView } from "@/components/settings/AccountSettingsView";
import { makeFakeClient } from "./_fakeClient";

// refreshCurrentUser is spied so AC-11 can assert it fires after a successful save.
const { refreshSpy } = vi.hoisted(() => ({ refreshSpy: vi.fn() }));

vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));
vi.mock("@/lib/useCurrentUser", () => ({
  useCurrentUser: () => ({
    user: { id: "u1", email: "sarah@acme.com", name: "Sarah Jenkins", title: "Legal Counsel" },
    displayName: "Sarah Jenkins",
    title: "Legal Counsel",
    email: "sarah@acme.com",
    loading: false,
  }),
  refreshCurrentUser: refreshSpy,
  displayNameFor: (u: { name?: string | null } | null) => u?.name ?? "there",
}));

beforeEach(() => {
  vi.mocked(getApiClient).mockReset();
  refreshSpy.mockReset();
});

describe("AccountSettingsView (spec 023 AC-9..12)", () => {
  test("renders_profile_and_security_tabs_with_readonly_email", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<AccountSettingsView />);

    expect(screen.getByRole("tab", { name: "Profile" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Security" })).toBeInTheDocument();

    expect(screen.getByLabelText(/full name/i)).toHaveValue("Sarah Jenkins");
    expect(screen.getByLabelText(/job title/i)).toHaveValue("Legal Counsel");
    const email = screen.getByLabelText(/email/i);
    expect(email).toHaveValue("sarah@acme.com");
    expect(email).toBeDisabled(); // AC-9
  });

  test("save_profile_calls_update_and_refreshes_shell", async () => {
    const client = makeFakeClient({});
    vi.mocked(getApiClient).mockReturnValue(client);
    render(<AccountSettingsView />);

    fireEvent.change(screen.getByLabelText(/full name/i), { target: { value: "Sarah J. Updated" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(client.updateProfile).toHaveBeenCalledWith({
        name: "Sarah J. Updated",
        title: "Legal Counsel",
      }),
    );
    await screen.findByText(/profile updated/i); // AC-10 success
    expect(refreshSpy).toHaveBeenCalled(); // AC-11
  });

  test("save_profile_error_shows_message_and_no_refresh", async () => {
    const client = makeFakeClient({ updateProfileError: new ApiError("boom", 500) });
    vi.mocked(getApiClient).mockReturnValue(client);
    render(<AccountSettingsView />);

    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await screen.findByText(/couldn.t update your profile/i); // AC-10 error
    expect(refreshSpy).not.toHaveBeenCalled();
  });

  test("change_password_mismatch_blocks_the_call", async () => {
    const client = makeFakeClient({});
    vi.mocked(getApiClient).mockReturnValue(client);
    render(<AccountSettingsView />);

    fireEvent.click(screen.getByRole("tab", { name: "Security" }));
    fireEvent.change(screen.getByLabelText("Current Password"), { target: { value: "OldPass1!" } });
    fireEvent.change(screen.getByLabelText("New Password"), { target: { value: "NewPassw1!" } });
    fireEvent.change(screen.getByLabelText("Confirm New Password"), { target: { value: "different" } });
    fireEvent.click(screen.getByRole("button", { name: /update password/i }));

    await screen.findByText(/don.t match/i); // AC-12
    expect(client.changePassword).not.toHaveBeenCalled();
  });

  test("change_password_success_clears_fields", async () => {
    const client = makeFakeClient({});
    vi.mocked(getApiClient).mockReturnValue(client);
    render(<AccountSettingsView />);

    fireEvent.click(screen.getByRole("tab", { name: "Security" }));
    fireEvent.change(screen.getByLabelText("Current Password"), { target: { value: "OldPass1!" } });
    fireEvent.change(screen.getByLabelText("New Password"), { target: { value: "NewPassw1!" } });
    fireEvent.change(screen.getByLabelText("Confirm New Password"), { target: { value: "NewPassw1!" } });
    fireEvent.click(screen.getByRole("button", { name: /update password/i }));

    await waitFor(() =>
      expect(client.changePassword).toHaveBeenCalledWith({
        current_password: "OldPass1!",
        new_password: "NewPassw1!",
      }),
    );
    await screen.findByText(/password updated/i); // AC-12 success
    expect(screen.getByLabelText("Current Password")).toHaveValue(""); // fields cleared
  });

  test("change_password_wrong_current_shows_backend_error", async () => {
    const client = makeFakeClient({
      changePasswordError: new ApiError("Current password is incorrect", 400),
    });
    vi.mocked(getApiClient).mockReturnValue(client);
    render(<AccountSettingsView />);

    fireEvent.click(screen.getByRole("tab", { name: "Security" }));
    fireEvent.change(screen.getByLabelText("Current Password"), { target: { value: "wrong" } });
    fireEvent.change(screen.getByLabelText("New Password"), { target: { value: "NewPassw1!" } });
    fireEvent.change(screen.getByLabelText("Confirm New Password"), { target: { value: "NewPassw1!" } });
    fireEvent.click(screen.getByRole("button", { name: /update password/i }));

    await screen.findByText(/current password is incorrect/i); // AC-12
  });
});
