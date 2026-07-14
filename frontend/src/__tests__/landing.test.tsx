/**
 * Landing page render test (AC-11): hero, CTAs, feature cards render without sidebar.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { LandingView } from "@/components/marketing/LandingView";

describe("LandingView (AC-11)", () => {
  it("renders the hero headline", () => {
    render(<LandingView />);
    expect(screen.getByText(/AI-Powered Legal Contract Intelligence/i)).toBeTruthy();
  });

  it("renders CTA that links to /login", () => {
    render(<LandingView />);
    const ctas = screen.getAllByRole("link");
    const loginLinks = ctas.filter((el) => el.getAttribute("href") === "/login");
    expect(loginLinks.length).toBeGreaterThan(0);
  });

  it("renders the feature cards", () => {
    render(<LandingView />);
    expect(screen.getByText(/Risk Scoring/i)).toBeTruthy();
    expect(screen.getByText(/Clause-by-Clause Explanation/i)).toBeTruthy();
  });

  it("does NOT render the app sidebar", () => {
    render(<LandingView />);
    // Sidebar has nav items like "Dashboard"; they must not appear here
    expect(screen.queryByText("Dashboard")).toBeNull();
  });
});
