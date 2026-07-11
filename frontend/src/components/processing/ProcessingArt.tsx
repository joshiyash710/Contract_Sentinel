import { ShieldCheck } from "lucide-react";

/**
 * Decorative glowing shield/document artwork for the processing screen (screen 6). No data, no
 * API — pure presentation built from the accent-gradient + glow tokens.
 */
export function ProcessingArt() {
  return (
    <div className="relative flex h-56 w-56 items-center justify-center">
      {/* stacked document cards */}
      <div className="absolute h-48 w-40 -rotate-6 rounded-card border border-subtle bg-card-raised/60" />
      <div className="absolute h-48 w-40 rotate-3 rounded-card border border-subtle bg-card" />
      {/* orbiting glow ring */}
      <div className="absolute h-52 w-52 animate-spin rounded-pill border-2 border-transparent border-t-accent border-r-accent/40 [animation-duration:6s]" />
      {/* shield */}
      <div className="relative flex h-24 w-24 items-center justify-center rounded-2xl bg-accent-gradient shadow-glow">
        <ShieldCheck size={44} className="text-accent-fg" />
      </div>
    </div>
  );
}
