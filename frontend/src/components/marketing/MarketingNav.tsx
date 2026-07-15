/**
 * Feature 019 — sticky, translucent landing nav. Log In / Sign Up route to /login (014 D8);
 * Features / Integrations are on-page anchors; Pricing / Blog are inert placeholders (no
 * fabricated destinations).
 */
import Link from "next/link";

export function MarketingNav() {
  return (
    <header className="sticky top-0 z-50 border-b border-subtle/60 bg-app/70 backdrop-blur-xl">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3.5">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-gradient text-accent-fg font-bold shadow-glow">
            C
          </span>
          <span className="text-h3 font-semibold tracking-tight text-text-primary">
            ContractSentinel
          </span>
        </Link>

        <nav className="hidden items-center gap-7 md:flex">
          <a href="#features" className="text-body text-text-secondary transition hover:text-text-primary">
            Features
          </a>
          <a href="#how" className="text-body text-text-secondary transition hover:text-text-primary">
            How it works
          </a>
          <a href="#features" className="text-body text-text-secondary transition hover:text-text-primary">
            Integrations
          </a>
          <span className="cursor-not-allowed text-body text-text-tertiary">Pricing</span>
          <span className="cursor-not-allowed text-body text-text-tertiary">Blog</span>
        </nav>

        <div className="flex items-center gap-3">
          <Link
            href="/login"
            className="rounded-input px-4 py-2 text-body font-medium text-text-secondary transition hover:text-text-primary"
          >
            Log In
          </Link>
          <Link
            href="/login"
            className="rounded-input bg-accent-gradient px-4 py-2 text-body font-semibold text-accent-fg shadow-glow transition hover:opacity-95"
          >
            Sign Up
          </Link>
        </div>
      </div>
    </header>
  );
}
