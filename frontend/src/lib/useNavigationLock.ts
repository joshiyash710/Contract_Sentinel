"use client";

import { useEffect } from "react";

/**
 * Locks the user on the current page while `active` is true. Used by the processing screen so a
 * running 7-agent pipeline can't be abandoned mid-flight by a browser Back/Forward, refresh, tab
 * close, or address-bar navigation (spec: "the user shouldn't be able to teleport to any other
 * page until the pipeline completes"). The focused processing route has no sidebar, so there are
 * no in-app links to intercept — this covers the remaining browser-level exits.
 *
 * Mechanism:
 *   - `beforeunload` → native "Leave site?" prompt for refresh / close / hard navigation.
 *   - a seeded duplicate history entry + `popstate` re-push → a Back/Forward press keeps the user
 *     on this page instead of leaving it.
 *
 * When `active` flips to false (pipeline finished/failed/errored) the listeners are torn down, so
 * the completion auto-redirect to the report proceeds normally.
 */
export function useNavigationLock(active: boolean): void {
  useEffect(() => {
    if (!active || typeof window === "undefined") return;

    // Capture the processing page's URL up front. This matters: by the time a `popstate` fires,
    // `window.location` ALREADY points at the page being navigated to, so re-pushing
    // `location.href` would just re-affirm the destination. We must re-assert THIS url instead.
    const lockedUrl = window.location.href;

    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      // Legacy requirement for the native confirmation prompt to appear.
      e.returnValue = "";
    };

    // Seed a duplicate history entry for THIS page. Because the entry behind the cursor now has
    // the same URL, a Back press doesn't actually change the path (so the router won't navigate
    // away); the popstate handler then re-seeds, keeping the user pinned here.
    const seed = () => window.history.pushState(null, "", lockedUrl);
    const onPopState = () => {
      seed();
      // Backstop: re-assert on the next frame in case the router already reacted to the pop.
      requestAnimationFrame(seed);
    };

    seed();
    window.addEventListener("beforeunload", onBeforeUnload);
    window.addEventListener("popstate", onPopState);

    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      window.removeEventListener("popstate", onPopState);
    };
  }, [active]);
}
