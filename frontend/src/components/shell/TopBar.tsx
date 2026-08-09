"use client";

import type { ReactNode } from "react";

/**
 * Top bar (spec AC-6): page title + optional search slot (present only when supplied —
 * screens 10/11/12). Sticky to the top of the content column.
 *
 * The former right-hand cluster (settings / notifications / profile avatar) was removed at
 * owner request: those controls were non-functional placeholders, and the real profile +
 * logout affordance already lives in the sidebar (UserProfileBlock).
 */
export function TopBar({
  title,
  search,
}: {
  title?: string;
  search?: ReactNode;
}) {
  return (
    <header className="glass gloss sticky top-0 z-20 flex items-center gap-4 border-b border-white/10 px-6 py-3">
      {title ? <h1 className="text-h2 font-bold text-text-primary">{title}</h1> : null}
      {search != null && <div className="mx-auto w-full max-w-xl">{search}</div>}
    </header>
  );
}
