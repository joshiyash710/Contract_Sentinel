import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { IntegrationsView } from "@/components/integrations/IntegrationsView";

// Control the owner email (and its absence) without touching the network.
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

beforeEach(() => {
  mockUser.email = "owner@acme.com";
});

describe("IntegrationsView (spec 024 AC-1..5)", () => {
  test("renders_drive_and_gmail_cards_with_delivery_descriptions", () => {
    render(<IntegrationsView />);
    expect(screen.getByRole("heading", { name: "Google Drive" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Gmail" })).toBeInTheDocument();
    // delivery-role descriptions (AC-3)
    expect(screen.getByText(/saved to google drive/i)).toBeInTheDocument();
    expect(screen.getByText(/emailed to you at/i)).toBeInTheDocument();
  });

  test("gmail_card_shows_owner_email", () => {
    render(<IntegrationsView />);
    expect(screen.getByText(/owner@acme\.com/)).toBeInTheDocument(); // AC-4
  });

  test("email_absent_falls_back_without_null_or_undefined", () => {
    mockUser.email = null;
    render(<IntegrationsView />);
    expect(screen.getByText(/your account email/i)).toBeInTheDocument(); // AC-4/EC-1
    expect(document.body.textContent).not.toMatch(/undefined|null/);
  });

  test("no_cut_integrations_shown", () => {
    render(<IntegrationsView />);
    expect(screen.queryByText(/notion|slack|dropbox|team/i)).not.toBeInTheDocument(); // AC-2
  });

  test("connect_affordance_is_disabled_and_not_an_oauth_link", () => {
    render(<IntegrationsView />);
    // No live OAuth link (AC-5)
    expect(screen.queryByRole("link", { name: /connect/i })).not.toBeInTheDocument();
    // Any managed/connect control is a disabled button
    const buttons = screen.queryAllByRole("button");
    for (const b of buttons) expect(b).toBeDisabled();
  });
});
