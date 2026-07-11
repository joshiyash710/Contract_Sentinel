import type { ReactNode } from "react";
import { Settings, Bell } from "lucide-react";
import { Avatar } from "@/components/ui/Avatar";

/**
 * Top bar (spec AC-6): page title + optional search slot (present only when supplied — screens
 * 10/11/12) + right cluster (settings, notifications-with-dot, avatar).
 */
export function TopBar({
  title,
  search,
  userName = "User Profile",
}: {
  title: string;
  search?: ReactNode;
  userName?: string;
}) {
  return (
    <header className="flex items-center gap-4 border-b border-subtle px-6 py-3">
      <h1 className="text-h2 font-bold text-text-primary">{title}</h1>
      {search != null && <div className="flex-1 max-w-md">{search}</div>}
      <div className="ml-auto flex items-center gap-3">
        <button aria-label="Settings" className="text-text-secondary hover:text-text-primary">
          <Settings size={18} />
        </button>
        <button aria-label="Notifications" className="relative text-text-secondary hover:text-text-primary">
          <Bell size={18} />
          <span
            data-testid="notif-dot"
            className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-pill bg-risk-high"
          />
        </button>
        <Avatar name={userName} size="sm" />
      </div>
    </header>
  );
}
