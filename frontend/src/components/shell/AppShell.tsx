"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "./Sidebar";
import { PUBLIC_ROUTES } from "@/lib/authRoutes";

/**
 * Composes the sidebar + content outlet (spec AC-7). Shell-free for public routes
 * (/, /login) so landing and auth pages render without the app sidebar (AC-11 / D16).
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  if (pathname && PUBLIC_ROUTES.includes(pathname)) {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-screen bg-app text-text-primary">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
