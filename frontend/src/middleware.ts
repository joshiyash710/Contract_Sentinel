import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { PUBLIC_ROUTES, isProtected } from "@/lib/authRoutes";

/**
 * Auth gate middleware (feature 014 / spec D5 / plan §4.2).
 *
 * Rules:
 *   - mock provider → always pass-through (mock-mode dev/tests are ungated)
 *   - protected path + no cs_session cookie → redirect /login  (AC-16)
 *   - / or /login WITH cs_session cookie   → redirect /dashboard (AC-17)
 *   - everything else → pass-through
 *
 * Presence-only check — the API is the real authority (D5 / EC-4).
 * The matcher excludes /_next, static assets, and /api (which guards itself).
 *
 * Exported as `middlewareHandler` for unit-testing (the function is pure and
 * has no Next server dependency beyond NextRequest/NextResponse shape).
 */
export function middlewareHandler(request: NextRequest): NextResponse | undefined {
  // Mock provider → ungated (D10 / plan §4.2)
  if (process.env.NEXT_PUBLIC_API_PROVIDER === "mock") {
    return NextResponse.next();
  }

  const { pathname } = request.nextUrl;
  const hasCookie = Boolean(request.cookies.get("cs_session"));

  // Authenticated user hitting a public route → send them in
  if (PUBLIC_ROUTES.includes(pathname) && hasCookie) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  // Unauthenticated user hitting a protected route → gate
  if (isProtected(pathname) && !hasCookie) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  return NextResponse.next();
}

export default middlewareHandler;

export const config = {
  matcher: [
    /*
     * Match all request paths EXCEPT:
     *   - /_next/static  (static files)
     *   - /_next/image   (image optimization)
     *   - /favicon.ico
     *   - /api           (API guards itself server-side)
     */
    "/((?!_next/static|_next/image|favicon.ico|api/).*)",
  ],
};
