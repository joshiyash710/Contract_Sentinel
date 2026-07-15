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
    <div className="min-h-screen bg-app text-text-primary">
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
