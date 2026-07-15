import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// Mock next/navigation's usePathname per test.
let currentPath = "/dashboard";
vi.mock("next/navigation", () => ({
  usePathname: () => currentPath,
  useRouter: () => ({ replace: vi.fn() }),
}));

import { Sidebar, NAV_ITEMS } from "@/components/shell/Sidebar";
import { TopBar } from "@/components/shell/TopBar";
import { AppShell } from "@/components/shell/AppShell";
import { UserProfileBlock } from "@/components/shell/UserProfileBlock";
import { SearchInput } from "@/components/ui/SearchInput";
import { getApiClient } from "@/lib/api/provider";
import { clearCurrentUser } from "@/lib/useCurrentUser";
import { authUserFixture } from "@/lib/api/fixtures";

describe("app shell", () => {
  beforeEach(() => {
    currentPath = "/dashboard";
    clearCurrentUser(); // reset the module-level current-user cache between tests
  });

  test("sidebar_five_items", () => {
    render(<Sidebar />);
    ["Dashboard", "Contracts", "Reports", "Integrations", "Settings"].forEach((label) =>
      expect(screen.getByText(label)).toBeInTheDocument(),
    );
    expect(NAV_ITEMS).toHaveLength(5);
  });

  test("contracts_item_links_to_history_and_active_there", () => {
    // Feature 021 D1: the Contracts nav points at the history list (/contracts), not /upload.
    currentPath = "/contracts";
    render(<Sidebar />);
    const contracts = screen.getByText("Contracts").closest("a");
    expect(contracts).toHaveAttribute("href", "/contracts");
    expect(contracts).toHaveAttribute("data-active", "true");
    expect(NAV_ITEMS).toHaveLength(5);
  });

  test("active_item_by_route", () => {
    currentPath = "/reports";
    const { rerender } = render(<Sidebar />);
    const reports = screen.getByText("Reports").closest("a");
    expect(reports).toHaveAttribute("data-active", "true");
    expect(screen.getByText("Dashboard").closest("a")).toHaveAttribute("data-active", "false");

    currentPath = "/dashboard";
    rerender(<Sidebar />);
    expect(screen.getByText("Dashboard").closest("a")).toHaveAttribute("data-active", "true");
  });

  test("integrations_expandable_variant", () => {
    render(<Sidebar />);
    // The Integrations item renders the chevron affordance (review N-1).
    expect(screen.getByTestId("nav-chevron")).toBeInTheDocument();
  });

  test("user_profile_block_prop_override", () => {
    const spy = vi.spyOn(getApiClient(), "getJob");
    render(<UserProfileBlock name="Ada Lovelace" role="Legal Counsel" />);
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Legal Counsel")).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled(); // no live-data (getJob) call (AC-5)
  });

  test("user_profile_block_shows_current_user", async () => {
    // Feature 020 (AC-7): with no props, the block shows the logged-in user's real name/title
    // from useCurrentUser (mock provider → authUserFixture), never the old "Sarah Jenkins".
    render(<UserProfileBlock />);
    expect(await screen.findByText(authUserFixture.name as string)).toBeInTheDocument();
    expect(screen.getByText(authUserFixture.title as string)).toBeInTheDocument();
    expect(screen.queryByText("Sarah Jenkins")).toBeNull();
  });

  test("topbar_slots", () => {
    const { rerender } = render(<TopBar title="AI Command Center" />);
    expect(screen.getByText("AI Command Center")).toBeInTheDocument();
    expect(screen.getByLabelText("Settings")).toBeInTheDocument();
    expect(screen.getByLabelText("Notifications")).toBeInTheDocument();
    expect(screen.getByTestId("notif-dot")).toBeInTheDocument();
    // search absent by default
    expect(screen.queryByRole("searchbox")).toBeNull();
    // present when supplied
    rerender(<TopBar title="X" search={<SearchInput />} />);
    expect(screen.getByRole("searchbox")).toBeInTheDocument();
  });

  test("layout_composes_outlet", () => {
    render(
      <AppShell>
        <div data-testid="outlet-child">Hello</div>
      </AppShell>,
    );
    // sidebar (nav) + top bar + the child are all present
    expect(screen.getByText("ContractSentinel")).toBeInTheDocument();
    expect(screen.getByTestId("outlet-child")).toBeInTheDocument();
  });
});
