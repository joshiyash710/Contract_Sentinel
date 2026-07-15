"use client";

import type { ReactNode } from "react";
import { Settings, Bell, ChevronDown } from "lucide-react";
import { Avatar } from "@/components/ui/Avatar";
import { useCurrentUser } from "@/lib/useCurrentUser";

/**
 * Top bar (spec AC-6): page title + optional search slot (present only when supplied — screens
 * 10/11/12) + right cluster (settings, notifications-with-dot, avatar). Sticky to the top of
 * the content column. The avatar name is the logged-in user (feature 020); `userName` prop
 * still overrides for tests.
 */
export function TopBar({
  title,
  search,
  userName,
  avatarSrc,
}: {
  title?: string;
  search?: ReactNode;
  userName?: string;
  avatarSrc?: string;
}) {
  const { displayName } = useCurrentUser();
  const shownName = userName ?? displayName ?? "User Profile";
  return (
    <header className="sticky top-0 z-20 flex items-center gap-4 border-b border-subtle bg-app/80 px-6 py-3 backdrop-blur">
      {title ? <h1 className="text-h2 font-bold text-text-primary">{title}</h1> : null}
      {search != null && <div className="mx-auto w-full max-w-xl">{search}</div>}
      <div className="ml-auto flex items-center gap-2">
        <button
          aria-label="Settings"
          className="flex h-9 w-9 items-center justify-center rounded-input text-text-secondary hover:bg-card-raised hover:text-text-primary"
        >
          <Settings size={18} />
        </button>
        <button
          aria-label="Notifications"
          className="relative flex h-9 w-9 items-center justify-center rounded-input text-text-secondary hover:bg-card-raised hover:text-text-primary"
        >
          <Bell size={18} />
          <span
            data-testid="notif-dot"
            className="absolute right-2 top-2 h-2 w-2 rounded-pill bg-risk-high ring-2 ring-app"
          />
        </button>
        <button className="flex items-center gap-1.5 rounded-pill py-0.5 pl-0.5 pr-2 hover:bg-card-raised">
          <Avatar name={shownName} src={avatarSrc} size="sm" />
          <ChevronDown size={16} className="text-text-tertiary" />
        </button>
      </div>
    </header>
  );
}
