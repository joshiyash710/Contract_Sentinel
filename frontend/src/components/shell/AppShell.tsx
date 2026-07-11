import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

/**
 * Composes the sidebar + top bar + content outlet (spec AC-7). `title` defaults for the
 * foundation demo; feature screens (014–018) pass their own title/search via the page.
 */
export function AppShell({
  children,
  title = "Dashboard",
}: {
  children: ReactNode;
  title?: string;
}) {
  return (
    <div className="flex min-h-screen bg-app text-text-primary">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <TopBar title={title} />
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  );
}
