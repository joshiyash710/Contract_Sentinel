/**
 * Feature 019 — feature strip, refreshed to the 2026-08 design-refs: the four primary
 * capabilities as a single row of cards with subtle dark icon chips. Anchored at #features.
 */
import { Contrast, AlignLeft, ArrowLeftRight, Settings2, type LucideIcon } from "lucide-react";

interface Feature {
  icon: LucideIcon;
  title: string;
  description: string;
}

const FEATURES: Feature[] = [
  {
    icon: Contrast,
    title: "Risk Scoring",
    description: "Quantified 0–100 risk per clause and per contract.",
  },
  {
    icon: AlignLeft,
    title: "Clause Explanation",
    description: "Plain-English breakdown of every legal clause.",
  },
  {
    icon: ArrowLeftRight,
    title: "Redline Rewrites",
    description: "AI-suggested safer language, ready to negotiate.",
  },
  {
    icon: Settings2,
    title: "Drive & Gmail",
    description: "Reports delivered straight to your workspace.",
  },
];

export function FeatureGrid() {
  return (
    <section id="features" className="px-6 pb-24">
      <div className="stagger mx-auto grid max-w-6xl gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {FEATURES.map(({ icon: Icon, title, description }) => (
          <div
            key={title}
            className="glass gloss lift sheen group relative rounded-card p-6 transition-colors hover:border-accent/30"
          >
            <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-accent transition-all duration-300 group-hover:border-accent/40 group-hover:bg-accent/10 group-hover:shadow-glow">
              <Icon size={19} />
            </div>
            <h3 className="mb-1.5 text-h3 font-semibold text-text-primary">{title}</h3>
            <p className="text-small leading-relaxed text-text-secondary">{description}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
