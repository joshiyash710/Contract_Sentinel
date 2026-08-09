/**
 * Feature 019 — closing CTA band + minimal footer. The CTA repeats the → /login action
 * (014 D8). Footer links are inert where no page exists (no fabricated destinations).
 */
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { LogoMark } from "@/components/ui/LogoMark";

export function ClosingCTA() {
  return (
    <>
      <section className="px-6 py-24">
        <div className="glass gloss reveal relative mx-auto max-w-5xl overflow-hidden rounded-[28px] px-8 py-16 text-center shadow-glow">
          {/* Drifting orbs inside the panel */}
          <div aria-hidden className="pointer-events-none absolute inset-0 -z-0">
            <div className="orb orb-a left-[6%] top-[-30%] h-72 w-72 bg-accent/25" />
            <div className="orb orb-b right-[4%] bottom-[-40%] h-72 w-72 bg-[color:var(--accent-cyan)]/20" />
          </div>
          <div className="relative">
            <h2 className="mx-auto max-w-2xl font-display text-3xl font-semibold tracking-tight text-text-primary md:text-4xl">
              Review your next contract with confidence
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-body text-text-secondary">
              Create a free account and analyze your first contract in minutes.
            </p>
            <Link
              href="/login"
              className="btn-gradient sheen press mt-9 inline-flex items-center gap-2 rounded-xl px-8 py-3.5 text-lg font-semibold text-accent-fg shadow-glow transition hover:brightness-110"
            >
              Get started free
              <ArrowRight size={18} />
            </Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-subtle px-6 py-10">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 sm:flex-row">
          <div className="flex items-center gap-2.5">
            <LogoMark size={28} />
            <span className="text-body font-semibold text-text-primary">ContractSentinel</span>
          </div>
          <div className="flex items-center gap-6 text-small text-text-tertiary">
            <a href="#features" className="transition hover:text-text-secondary">
              Features
            </a>
            <a href="#how" className="transition hover:text-text-secondary">
              How it works
            </a>
            <Link href="/login" className="transition hover:text-text-secondary">
              Log In
            </Link>
          </div>
          <p className="text-caption text-text-tertiary">
            © {new Date().getFullYear()} ContractSentinel
          </p>
        </div>
      </footer>
    </>
  );
}
