"use client";

import { useEffect, useState } from "react";
import { getApiClient } from "@/lib/api/provider";
import { ApiError } from "@/lib/api/client";
import type { AuthUser } from "@/lib/api/types";

/**
 * Feature 020 — the logged-in user for the app shell (sidebar + top bar). Calls
 * getApiClient().me() once and shares the in-flight promise at module scope so the sidebar and
 * top bar don't double-fetch per navigation. Never throws into the tree: on any error
 * (e.g. a 401) it yields no user, and the route gate/middleware handles the redirect.
 * Call clearCurrentUser() on logout so a re-login as a different account re-fetches.
 */

let _cached: Promise<AuthUser | null> | null = null;
// Set true ONLY when /me returns a 401 (genuinely unauthenticated — invalid/expired/absent session),
// distinct from a transient network blip. The shell's auth guard reads this to redirect to landing.
let _unauthenticated = false;
// Mounted useCurrentUser instances subscribe so a profile edit (023) live-updates the
// shell (Sidebar/TopBar) without a full reload.
const _subscribers = new Set<() => void>();

function fetchCurrentUser(): Promise<AuthUser | null> {
  if (_cached) return _cached;
  const p = getApiClient()
    .me()
    .then((u) => {
      _unauthenticated = false;
      return u;
    })
    .catch((err) => {
      // A 401 means the session is invalid/expired/absent → the guard should redirect to landing.
      // Any OTHER error (e.g. an API blip during a heavy analysis run) is transient: don't flag
      // unauthenticated and don't cache the failure, so the next read re-fetches the real user.
      _unauthenticated = err instanceof ApiError && err.status === 401;
      if (_cached === p) _cached = null;
      return null;
    });
  _cached = p;
  return p;
}

/** True only after /me returned a 401 (invalid/expired/absent session), not on transient errors. */
export function isUnauthenticated(): boolean {
  return _unauthenticated;
}

export function clearCurrentUser(): void {
  _cached = null;
}

/**
 * Feature 023 — after a profile save, drop the cache, re-fetch, and notify every mounted
 * useCurrentUser so the sidebar/top bar reflect the new name/title immediately.
 */
export async function refreshCurrentUser(): Promise<void> {
  _cached = null;
  await fetchCurrentUser();
  _subscribers.forEach((fn) => fn());
}

function emailLocalPart(email?: string | null): string {
  if (!email) return "";
  const at = email.indexOf("@");
  return at > 0 ? email.slice(0, at) : email;
}

/** Display name: real name if present, else the email's local part, else a neutral fallback. */
export function displayNameFor(user: AuthUser | null): string {
  const n = user?.name?.trim();
  if (n) return n;
  return emailLocalPart(user?.email) || "there";
}

export interface CurrentUserState {
  user: AuthUser | null;
  displayName: string;
  title: string | null;
  email: string | null;
  loading: boolean;
  /** True only when /me returned a 401 (invalid/expired/absent session), not on a transient error. */
  unauthenticated: boolean;
}

export function useCurrentUser(): CurrentUserState {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [unauthenticated, setUnauthenticated] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchCurrentUser().then((u) => {
        if (cancelled) return;
        setUser(u);
        setUnauthenticated(u === null && isUnauthenticated());
        setLoading(false);
      });
    load();
    // Re-read on refreshCurrentUser() (023 profile save).
    const bump = () => {
      load();
    };
    _subscribers.add(bump);
    return () => {
      cancelled = true;
      _subscribers.delete(bump);
    };
  }, []);

  return {
    user,
    displayName: displayNameFor(user),
    title: user?.title ?? null,
    email: user?.email ?? null,
    loading,
    unauthenticated,
  };
}
