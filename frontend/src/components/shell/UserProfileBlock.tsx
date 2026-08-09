"use client";

import { LogOut } from "lucide-react";
import { Avatar } from "@/components/ui/Avatar";
import { getApiClient } from "@/lib/api/provider";
import { useCurrentUser } from "@/lib/useCurrentUser";

/**
 * Sidebar-bottom profile block (avatar + name + title + logout). The name/title come from the
 * logged-in user via useCurrentUser (feature 020); optional props still override for tests.
 * Logout ends the server session then hard-redirects to /login (014 AC-15).
 */
export function UserProfileBlock({
  name,
  role,
  avatarSrc,
}: {
  name?: string;
  role?: string;
  avatarSrc?: string;
}) {
  const { displayName, title } = useCurrentUser();
  const shownName = name ?? displayName;
  const shownRole = role ?? title ?? undefined;

  async function handleLogout() {
    try {
      await getApiClient().logout();
    } catch {
      // Always redirect even on error — the cookie is cleared server-side
    }
    // Auth boundary: HARD navigation (full document load), not router.replace, so
    // Next's Router Cache and every mounted client component are destroyed. This
    // prevents the next account's session from ever reusing this user's cached
    // /dashboard render (their data/name). Full reload also clears the in-memory
    // current-user cache, so no explicit clearCurrentUser() is needed.
    window.location.assign("/login");
  }

  return (
    <div className="glass gloss m-3 flex items-center gap-3 rounded-card px-3 py-3">
      <Avatar name={shownName} src={avatarSrc} size="md" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-body font-medium text-text-primary">{shownName}</div>
        {shownRole ? (
          <div className="truncate text-small text-text-secondary">{shownRole}</div>
        ) : null}
      </div>
      <button
        type="button"
        onClick={handleLogout}
        aria-label="Log out"
        title="Log out"
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-text-tertiary hover:bg-card-raised hover:text-text-secondary transition"
      >
        <LogOut size={16} />
      </button>
    </div>
  );
}
