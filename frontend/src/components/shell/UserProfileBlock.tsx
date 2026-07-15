"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { Avatar } from "@/components/ui/Avatar";
import { getApiClient } from "@/lib/api/provider";
import { useCurrentUser, clearCurrentUser } from "@/lib/useCurrentUser";

/**
 * Sidebar-bottom profile block (avatar + name + title + logout). The name/title come from the
 * logged-in user via useCurrentUser (feature 020); optional props still override for tests.
 * Logout clears the cached user then redirects to /login (014 AC-15).
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
  const router = useRouter();
  const { displayName, title } = useCurrentUser();
  const shownName = name ?? displayName;
  const shownRole = role ?? title ?? undefined;

  async function handleLogout() {
    try {
      await getApiClient().logout();
    } catch {
      // Always redirect even on error — the cookie is cleared server-side
    }
    clearCurrentUser();
    router.replace("/login");
  }

  return (
    <div className="flex items-center gap-3 border-t border-subtle px-4 py-4">
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
