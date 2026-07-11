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
        "flex items-center gap-3 rounded-input px-3 py-2 text-body transition",
        active
          ? "bg-accent-gradient text-accent-fg font-medium shadow-glow"
          : "text-text-secondary hover:bg-card-raised hover:text-text-primary",
      )}
    >
      <Icon size={18} />
      <span className="flex-1">{item.label}</span>
      {item.expandable && <ChevronDown size={16} className="opacity-70" data-testid="nav-chevron" />}
    </Link>
  );
}
