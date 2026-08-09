"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown } from "lucide-react";
import type { NavItem } from "./Sidebar";

export function SidebarNavItem({ item }: { item: NavItem }) {
  const pathname = usePathname();
  const active = pathname === item.href || pathname?.startsWith(`${item.href}/`);
  const Icon = item.icon;

  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      data-active={active ? "true" : "false"}
      className={clsx(
        "relative flex items-center gap-3 rounded-input px-3 py-2.5 text-body transition-colors",
        active
          ? "bg-accent/10 text-text-primary font-semibold ring-1 ring-accent/25"
          : "text-text-secondary hover:bg-card-raised/60 hover:text-text-primary",
      )}
    >
      {active && (
        <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r bg-accent" />
      )}
      <Icon size={18} className={active ? "text-accent" : ""} />
      <span className="flex-1">{item.label}</span>
      {item.expandable && (
        <ChevronDown
          size={16}
          className={active ? "opacity-80" : "opacity-50"}
          data-testid="nav-chevron"
        />
      )}
    </Link>
  );
}
