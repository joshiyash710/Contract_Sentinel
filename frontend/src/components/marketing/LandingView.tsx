/**
 * Feature 019 — premium marketing landing (`/`). Composed from section components; renders
 * shell-free (the conditional AppShell keeps `/` sidebar-less). No provider import (seam).
 * Preserves 014 D8 (CTAs → /login; Pricing/Blog inert).
 */
import { MarketingNav } from "./MarketingNav";
import { Hero } from "./Hero";
import { FeatureGrid } from "./FeatureGrid";
import { HowItWorks } from "./HowItWorks";
import { ClosingCTA } from "./ClosingCTA";

export function LandingView() {
  return (
    <div className="relative min-h-screen overflow-hidden text-text-primary">
      {/* Atmosphere: a faint blueprint grid + a couple of soft, low-key drifting orbs (kept
          restrained so the look stays dark and premium rather than washed in glow). */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="grid-overlay opacity-70" />
        <div className="orb orb-a left-[-12%] top-[-8%] h-[38rem] w-[38rem] bg-accent/12" />
        <div className="orb orb-b right-[-6%] top-[4%] h-[34rem] w-[34rem] bg-[color:var(--accent-gradient-to)]/12" />
      </div>

      <MarketingNav />
      <main>
        <Hero />
        <FeatureGrid />
        <HowItWorks />
        <ClosingCTA />
      </main>
    </div>
  );
}
