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
    // The headline is split across a gradient <span>, so match the h1's text content.
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toMatch(/AI-Powered Legal Contract Intelligence/i);
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

  it("renders the 'How it works' section (AC-B1)", () => {
    render(<LandingView />);
    expect(screen.getByRole("heading", { name: /how it works/i })).toBeTruthy();
  });

  it("renders a closing call-to-action (AC-B1)", () => {
    render(<LandingView />);
    // The closing band repeats a Get started / free CTA to /login.
    const loginLinks = screen
      .getAllByRole("link")
      .filter((el) => el.getAttribute("href") === "/login");
    // hero CTA + nav Log In + nav Sign Up + closing CTA → several links to /login
    expect(loginLinks.length).toBeGreaterThanOrEqual(3);
  });

  it("Log In and Sign Up both link to /login (AC-B2)", () => {
    render(<LandingView />);
    // "Log In" appears in the nav and footer; every one must point to /login.
    const logins = screen.getAllByRole("link", { name: /log in/i });
    expect(logins.length).toBeGreaterThan(0);
    logins.forEach((l) => expect(l.getAttribute("href")).toBe("/login"));
    // "Sign Up" is nav-only.
    expect(screen.getByRole("link", { name: /sign up/i }).getAttribute("href")).toBe("/login");
  });

  it("does NOT render the app sidebar", () => {
    render(<LandingView />);
    // Sidebar has nav items like "Dashboard"; they must not appear here
    expect(screen.queryByText("Dashboard")).toBeNull();
  });
});
