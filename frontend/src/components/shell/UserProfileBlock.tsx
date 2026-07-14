"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { Avatar } from "@/components/ui/Avatar";
import { getApiClient } from "@/lib/api/provider";

/**
 * Sidebar-bottom profile block (avatar + name + role + logout).
 * Logout calls apiClient.logout() then redirects to /login (AC-15 / D1).
 */
export function UserProfileBlock({
  name,
  role,
  avatarSrc,
}: {
  name: string;
  role?: string;
  avatarSrc?: string;
}) {
  const router = useRouter();

  async function handleLogout() {
    try {
      await getApiClient().logout();
    } catch {
      // Always redirect even on error — the cookie is cleared server-side
    }
    router.replace("/login");
  }

  return (
    <div className="flex items-center gap-3 border-t border-subtle px-4 py-4">
      <Avatar name={name} src={avatarSrc} size="md" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-body font-medium text-text-primary">{name}</div>
        {role ? <div className="truncate text-small text-text-secondary">{role}</div> : null}
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
