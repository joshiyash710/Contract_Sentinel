/**
 * Feature 019 — hero. Aurora backdrop, gradient headline, primary CTA → /login (014 D8),
 * secondary "See how it works" anchor, and the shield/documents artwork.
 */
import Link from "next/link";
import { Shield, ArrowRight, Sparkles } from "lucide-react";
import { HeroArt } from "./HeroArt";

export function Hero() {
  return (
    <section className="bg-aurora">
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-6 py-20 md:grid-cols-2 md:py-28">
        <div>
          <div className="mb-6 inline-flex items-center gap-2 rounded-pill border border-subtle bg-card-raised/70 px-4 py-1.5 text-small text-text-secondary backdrop-blur">
            <Sparkles size={14} className="text-accent" />
            AI-Powered Legal Intelligence
          </div>

          <h1 className="text-4xl font-extrabold leading-[1.05] tracking-tight text-text-primary md:text-6xl">
            AI-Powered Legal{" "}
            <span className="bg-accent-gradient bg-clip-text text-transparent">
              Contract Intelligence
            </span>
          </h1>

          <p className="mt-6 max-w-xl text-lg leading-relaxed text-text-secondary">
            Understand your legal contracts before you sign. Instantly identify risks, clarify
            terms, and save thousands on legal fees — in seconds, not hours.
          </p>

          <div className="mt-9 flex flex-wrap items-center gap-4">
            <Link
              href="/login"
              className="inline-flex items-center gap-2 rounded-xl bg-accent-gradient px-7 py-3.5 text-lg font-semibold text-accent-fg shadow-glow transition hover:opacity-95"
            >
              Analyze Your First Contract (Free)
              <ArrowRight size={18} />
            </Link>
            <a
              href="#how"
              className="inline-flex items-center gap-2 rounded-xl border border-subtle px-6 py-3.5 text-body font-medium text-text-secondary transition hover:border-text-secondary hover:text-text-primary"
            >
              See how it works
            </a>
          </div>

          <div className="mt-8 flex items-center gap-6 text-small text-text-tertiary">
            <span className="inline-flex items-center gap-1.5">
              <Shield size={14} className="text-risk-low" /> Private by design
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Sparkles size={14} className="text-accent" /> Evidence-backed findings
            </span>
          </div>
        </div>

        <HeroArt />
      </div>
    </section>
  );
}
