/**
 * Route classification for the auth gate (feature 014 / spec D5 / plan §4.2).
 * Shared by middleware.ts and AppShell.tsx so there is one source of truth.
 */
export const PUBLIC_ROUTES: string[] = ["/", "/login"];

/**
 * Returns true if the pathname requires authentication.
 * Next internal paths (_next/static, _next/image, /api, favicon.ico) are never
 * gated — the middleware config.matcher excludes them, but this helper is also
 * safe to call on those paths.
 */
export function isProtected(pathname: string): boolean {
  if (PUBLIC_ROUTES.includes(pathname)) return false;
  if (pathname.startsWith("/_next")) return false;
  if (pathname.startsWith("/api")) return false;
  if (pathname === "/favicon.ico") return false;
  return true;
}
