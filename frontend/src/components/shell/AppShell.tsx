import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";

/**
 * Composes the sidebar + content outlet (spec AC-7). The TopBar is rendered per-page (each
 * screen owns its title / optional search), matching the reference designs where the Command
 * Center shows a centered search while the Risk Dashboard shows a left-aligned title.
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen bg-app text-text-primary">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
