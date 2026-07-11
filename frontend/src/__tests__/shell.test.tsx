import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// Mock next/navigation's usePathname per test.
let currentPath = "/dashboard";
vi.mock("next/navigation", () => ({
  usePathname: () => currentPath,
}));

import { Sidebar, NAV_ITEMS } from "@/components/shell/Sidebar";
import { TopBar } from "@/components/shell/TopBar";
import { AppShell } from "@/components/shell/AppShell";
import { UserProfileBlock } from "@/components/shell/UserProfileBlock";
import { SearchInput } from "@/components/ui/SearchInput";
import { getApiClient } from "@/lib/api/provider";

describe("app shell", () => {
  beforeEach(() => {
    currentPath = "/dashboard";
  });

  test("sidebar_five_items", () => {
    render(<Sidebar />);
    ["Dashboard", "Contracts", "Reports", "Integrations", "Settings"].forEach((label) =>
      expect(screen.getByText(label)).toBeInTheDocument(),
    );
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

  test("user_profile_block", () => {
    const spy = vi.spyOn(getApiClient(), "getJob");
    render(<UserProfileBlock name="Ada Lovelace" role="Legal Counsel" />);
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Legal Counsel")).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled(); // no auth/backend call (AC-5)
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
