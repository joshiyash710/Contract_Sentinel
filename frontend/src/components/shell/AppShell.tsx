"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "./Sidebar";
import { PUBLIC_ROUTES } from "@/lib/authRoutes";
import { getApiClient } from "@/lib/api/provider";
import { useCurrentUser, clearCurrentUser } from "@/lib/useCurrentUser";

/**
 * Composes the sidebar + content outlet (spec AC-7). Shell-free for public routes
 * (/, /login) so landing and auth pages render without the app sidebar (AC-11 / D16).
 *
 * Feature 032 (W2): the auth middleware only checks cookie PRESENCE, so a stale/expired/invalid
 * cs_session (e.g. an idle-timed-out, epoch-invalidated, or pre-032 token) is waved through to a
 * protected route. The ProtectedShell guard below confirms with the API: on a genuine 401 it clears
 * the stale cookie server-side and sends the user to the landing page — never a phantom "there"
 * dashboard.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  if (pathname && PUBLIC_ROUTES.includes(pathname)) {
    return <>{children}</>;
  }

  // The live processing route (/jobs/<id>, but NOT /jobs/<id>/report) is a focused, chrome-less
  // screen: no sidebar, so the running pipeline can't be abandoned via an in-app nav link.
  const focused = /^\/jobs\/[^/]+$/.test(pathname ?? "");

  return <ProtectedShell chromeless={focused}>{children}</ProtectedShell>;
}

function ProtectedShell({
  children,
  chromeless = false,
}: {
  children: ReactNode;
  chromeless?: boolean;
}) {
  const { user, loading, unauthenticated } = useCurrentUser();
  const redirecting = useRef(false);

  useEffect(() => {
    if (loading || redirecting.current) return;
    if (unauthenticated) {
      redirecting.current = true;
      // Stale/expired/invalid session on a protected route: clear the httpOnly cookie via the
      // backend (so the presence-only middleware stops bouncing us back here), drop the cached
      // user, then land on the public home page.
      void (async () => {
        try {
          await getApiClient().logout();
        } catch {
          /* best effort — redirect regardless */
        }
        clearCurrentUser();
        if (typeof window !== "undefined") window.location.assign("/");
      })();
    }
  }, [loading, unauthenticated]);

  // Don't render the dashboard shell for a not-yet-confirmed or unauthenticated user — that's what
  // produced the phantom "there" dashboard. Show a minimal placeholder while we resolve/redirect.
  if (loading || !user) {
    return <div className="min-h-screen bg-app" aria-busy="true" />;
  }

  // Focused screens (live processing) render full-width with no sidebar so the running pipeline
  // can't be navigated away from via the nav.
  if (chromeless) {
    return <div className="min-h-screen text-text-primary">{children}</div>;
  }

  return (
    <div className="flex min-h-screen text-text-primary">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
