"use client";

import { LayoutDashboard, FileText, BarChart3, Plug, Settings } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { SidebarNavItem } from "./SidebarNavItem";
import { UserProfileBlock } from "./UserProfileBlock";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  expandable?: boolean;
}

// Data-driven so 014–018 don't rebuild the nav. Q3: all five items; Integrations =
// Drive+Gmail only (Q2), expandable chevron variant (review N-1).
export const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/contracts", label: "Contracts", icon: FileText },
  { href: "/reports", label: "Reports", icon: BarChart3 },
  { href: "/integrations", label: "Integrations", icon: Plug, expandable: true },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  return (
    <aside className="flex w-60 shrink-0 flex-col bg-sidebar border-r border-subtle">
      <div className="flex items-center gap-2 px-5 py-5">
        <span className="flex h-7 w-7 items-center justify-center rounded-pill bg-accent-gradient text-accent-fg font-bold">
          C
        </span>
        <span className="text-h3 font-semibold text-text-primary">ContractSentinel</span>
      </div>
      <nav className="flex flex-1 flex-col gap-1 px-3">
        {NAV_ITEMS.map((item) => (
          <SidebarNavItem key={item.href} item={item} />
        ))}
      </nav>
      <UserProfileBlock name="User Profile" role="" />
    </aside>
  );
}
