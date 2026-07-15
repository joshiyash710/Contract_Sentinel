"use client";

import { useEffect, useState } from "react";
import { getApiClient } from "@/lib/api/provider";
import type { AuthUser } from "@/lib/api/types";

/**
 * Feature 020 — the logged-in user for the app shell (sidebar + top bar). Calls
 * getApiClient().me() once and shares the in-flight promise at module scope so the sidebar and
 * top bar don't double-fetch per navigation. Never throws into the tree: on any error
 * (e.g. a 401) it yields no user, and the route gate/middleware handles the redirect.
 * Call clearCurrentUser() on logout so a re-login as a different account re-fetches.
 */

let _cached: Promise<AuthUser | null> | null = null;

function fetchCurrentUser(): Promise<AuthUser | null> {
  if (_cached) return _cached;
  _cached = getApiClient()
    .me()
    .then((u) => u)
    .catch(() => null);
  return _cached;
}

export function clearCurrentUser(): void {
  _cached = null;
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
}

export function useCurrentUser(): CurrentUserState {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchCurrentUser().then((u) => {
      if (cancelled) return;
      setUser(u);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return {
    user,
    displayName: displayNameFor(user),
    title: user?.title ?? null,
    email: user?.email ?? null,
    loading,
  };
}
