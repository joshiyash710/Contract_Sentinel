/**
 * Feature 019 — hero, refreshed to the 2026-08 design-refs. Status pill, serif display
 * headline with gradient accent words, primary CTA → /login (014 D8), a secondary "Watch demo"
 * button, a stats strip, and a product-screenshot mockup (HeroArt).
 */
import Link from "next/link";
import { ArrowRight, Play } from "lucide-react";
import { HeroArt } from "./HeroArt";

const STATS: { value: string; label: string }[] = [
  { value: "12k+", label: "contracts analyzed" },
  { value: "98.4%", label: "clause accuracy" },
  { value: "4.2m", label: "risks flagged" },
];

export function Hero() {
  return (
    <section className="relative">
      <div className="mx-auto grid max-w-7xl items-center gap-x-12 gap-y-12 px-6 py-20 md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] md:py-28 lg:gap-x-20">
        <div className="reveal">
          <div className="glass mb-7 inline-flex items-center gap-2 rounded-pill px-4 py-1.5 text-small font-medium text-text-secondary">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-risk-low opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-risk-low shadow-[0_0_8px_var(--risk-low)]" />
            </span>
            Powered by autonomous legal AI agents
          </div>

          <h1 className="font-display text-5xl font-semibold leading-[1.05] tracking-tight text-text-primary md:text-[4.25rem]">
            <span className="block whitespace-nowrap">
              AI-Powered <span className="gradient-animate">Legal</span>
            </span>{" "}
            <span className="block whitespace-nowrap">
              Contract <span className="gradient-animate">Intelligence</span>
            </span>
          </h1>

          <p className="mt-6 max-w-xl text-lg leading-relaxed text-text-secondary">
            Understand your legal contracts before you sign. Instantly identify risks, clarify
            terms, and save thousands on legal fees.
          </p>

          <div className="mt-9 flex flex-wrap items-center gap-4">
            <Link
              href="/login"
              className="btn-gradient sheen press inline-flex items-center gap-2 rounded-xl px-7 py-3.5 text-body font-semibold text-accent-fg shadow-glow transition hover:brightness-110"
            >
              Analyze Your First Contract — Free
              <ArrowRight size={18} />
            </Link>
            <a
              href="#how"
              className="glass press inline-flex items-center gap-2 rounded-xl px-6 py-3.5 text-body font-medium text-text-primary transition hover:bg-white/10"
            >
              <Play size={15} className="fill-current text-accent" /> Watch demo
            </a>
          </div>

          <div className="stagger mt-11 flex items-center gap-10">
            {STATS.map(({ value, label }) => (
              <div key={label}>
                <div className="font-display text-3xl font-semibold text-text-primary">{value}</div>
                <div className="mt-0.5 text-small text-text-tertiary">{label}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="reveal w-full max-w-md justify-self-center md:justify-self-end">
          <HeroArt />
        </div>
      </div>
    </section>
  );
}
