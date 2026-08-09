/**
 * Feature 019 — sticky, translucent landing nav. Log In / Sign Up route to /login (014 D8);
 * Features / Integrations are on-page anchors; Pricing / Blog are inert placeholders (no
 * fabricated destinations).
 */
import Link from "next/link";
import { LogoMark } from "@/components/ui/LogoMark";

const NAV_LINK =
  "relative text-body text-text-secondary transition-colors hover:text-text-primary after:absolute after:-bottom-1 after:left-0 after:h-px after:w-0 after:bg-accent-gradient after:transition-all after:duration-300 hover:after:w-full";

export function MarketingNav() {
  return (
    <div className="sticky top-0 z-50 px-4 pt-4">
      <header className="glass-nav reveal mx-auto flex max-w-6xl items-center justify-between rounded-2xl border border-white/10 px-5 py-3 shadow-[0_16px_40px_-16px_rgba(0,0,0,0.7)]">
        <Link href="/" className="flex items-center gap-2.5">
          <LogoMark size={32} />
          <span className="font-display text-h3 font-semibold tracking-tight text-text-primary">
            Contract<span className="bg-accent-gradient bg-clip-text text-transparent">Sentinel</span>
          </span>
        </Link>

        <nav className="hidden items-center gap-8 md:flex">
          <a href="#features" className={NAV_LINK}>
            Features
          </a>
          <a href="#how" className={NAV_LINK}>
            Integrations
          </a>
          <span className="cursor-not-allowed text-body text-text-tertiary">Pricing</span>
          <span className="cursor-not-allowed text-body text-text-tertiary">Blog</span>
        </nav>

        <div className="flex items-center gap-3">
          <Link
            href="/login"
            className="glass rounded-pill px-5 py-2 text-body font-medium text-text-primary transition hover:bg-white/10"
          >
            Log In
          </Link>
          <Link
            href="/login"
            className="btn-gradient press rounded-pill px-5 py-2 text-body font-semibold text-accent-fg shadow-glow transition hover:brightness-110"
          >
            Sign Up
          </Link>
        </div>
      </header>
    </div>
  );
}
