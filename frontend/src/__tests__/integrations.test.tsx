import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { IntegrationsView } from "@/components/integrations/IntegrationsView";

// Control the owner email without touching the network.
const mockUser: { email: string | null } = { email: "owner@acme.com" };
vi.mock("@/lib/useCurrentUser", () => ({
  useCurrentUser: () => ({
    user: null,
    displayName: "there",
    title: null,
    email: mockUser.email,
    loading: false,
  }),
}));

// Feature 031: mock the API client seam for the per-user Drive connect.
const driveState: { connected: boolean; googleEmail?: string | null } = { connected: false };
const disconnectSpy = vi.fn(async () => {
  driveState.connected = false; // mirror the backend clearing the connection
});
// Stable client object (getApiClient returns the same reference each call).
const _fakeClient = {
  getGoogleDriveStatus: async () => ({ ...driveState }),
  googleDriveAuthorizeUrl: () => "http://localhost:8000/api/integrations/google/authorize",
  disconnectGoogleDrive: disconnectSpy,
};
vi.mock("@/lib/api/provider", () => ({
  getApiClient: () => _fakeClient,
}));

beforeEach(() => {
  mockUser.email = "owner@acme.com";
  driveState.connected = false;
  driveState.googleEmail = null;
  disconnectSpy.mockClear();
});

describe("IntegrationsView (feature 031 per-user Drive)", () => {
  test("renders_drive_and_gmail_cards", () => {
    render(<IntegrationsView />);
    expect(screen.getByRole("heading", { name: "Google Drive" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Gmail" })).toBeInTheDocument();
    expect(screen.getByText(/saved to your own google drive/i)).toBeInTheDocument();
    expect(screen.getByText(/emailed to you at/i)).toBeInTheDocument();
  });

  test("gmail_card_shows_owner_email_and_stays_server_managed", () => {
    render(<IntegrationsView />);
    expect(screen.getByText(/owner@acme\.com/)).toBeInTheDocument();
    expect(screen.getByText(/server-managed/i)).toBeInTheDocument();
  });

  test("not_connected_shows_connect_button", async () => {
    render(<IntegrationsView />);
    expect(
      await screen.findByRole("button", { name: /connect google drive/i }),
    ).toBeInTheDocument();
  });

  test("connected_shows_email_and_disconnect", async () => {
    driveState.connected = true;
    driveState.googleEmail = "me@gmail.com";
    render(<IntegrationsView />);
    expect(await screen.findByText(/connected as me@gmail\.com/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /disconnect/i })).toBeInTheDocument();
  });

  test("disconnect_calls_the_seam_and_reverts_to_connect", async () => {
    driveState.connected = true;
    driveState.googleEmail = "me@gmail.com";
    render(<IntegrationsView />);
    fireEvent.click(await screen.findByRole("button", { name: /disconnect/i }));
    await waitFor(() => expect(disconnectSpy).toHaveBeenCalledOnce());
    expect(
      await screen.findByRole("button", { name: /connect google drive/i }),
    ).toBeInTheDocument();
  });

  test("email_absent_falls_back_without_null_or_undefined", () => {
    mockUser.email = null;
    render(<IntegrationsView />);
    expect(screen.getByText(/your account email/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/undefined|null/);
  });

  test("no_cut_integrations_shown", () => {
    render(<IntegrationsView />);
    expect(screen.queryByText(/notion|slack|dropbox|team/i)).not.toBeInTheDocument();
  });
});
