"use client";

import Link from "next/link";
import { Shield, FileSearch, GitCompare, Plug } from "lucide-react";

const FEATURES = [
  {
    icon: Shield,
    title: "Risk Scoring",
    description:
      "Every clause gets an AI-derived risk level — High, Medium, or Low — so you know exactly where to focus.",
  },
  {
    icon: FileSearch,
    title: "Clause-by-Clause Explanation",
    description:
      "Plain-English rationale for every flagged clause, backed by evidence from our legal knowledge base.",
  },
  {
    icon: GitCompare,
    title: "Contract Comparison",
    description:
      "Side-by-side redline suggestions generated automatically, ready for your counterparty.",
  },
  {
    icon: Plug,
    title: "Integration Ecosystem",
    description:
      "Push reports directly to Google Drive and notify stakeholders via Gmail in one click.",
  },
];

export function LandingView() {
  return (
    <div className="min-h-screen bg-app text-text-primary">
      {/* Nav */}
      <header className="border-b border-subtle px-6 py-4">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-gradient text-accent-fg font-bold shadow-glow">
              C
            </span>
            <span className="text-h3 font-semibold tracking-tight text-text-primary">
              ContractSentinel
            </span>
          </div>
          <nav className="hidden items-center gap-6 md:flex">
            {/* Features anchors to the on-page section (D8). Pricing/Blog are inert. */}
            <a href="#features" className="text-body text-text-secondary hover:text-text-primary transition">
              Features
            </a>
            <a href="#features" className="text-body text-text-secondary hover:text-text-primary transition">
              Integrations
            </a>
            <span className="cursor-not-allowed text-body text-text-tertiary">Pricing</span>
            <span className="cursor-not-allowed text-body text-text-tertiary">Blog</span>
          </nav>
          <div className="flex items-center gap-3">
            <Link
              href="/login"
              className="rounded-lg border border-subtle px-4 py-2 text-body font-medium text-text-secondary hover:border-text-secondary transition"
            >
              Log In
            </Link>
            <Link
              href="/login"
              className="rounded-lg bg-accent px-4 py-2 text-body font-semibold text-accent-fg shadow-glow hover:opacity-90 transition"
            >
              Sign Up
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="px-6 py-24 text-center">
        <div className="mx-auto max-w-3xl">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-subtle bg-card-raised px-4 py-1.5 text-small text-text-secondary">
            <Shield size={14} className="text-accent" />
            AI-Powered Legal Intelligence
          </div>
          <h1 className="mb-6 text-4xl font-bold leading-tight tracking-tight text-text-primary md:text-5xl">
            AI-Powered Legal Contract Intelligence
          </h1>
          <p className="mb-10 text-lg text-text-secondary">
            Automatically surface risk, explain every clause, and generate redlines — in seconds,
            not hours.
          </p>
          <Link
            href="/login"
            className="inline-flex items-center gap-2 rounded-xl bg-accent px-8 py-3.5 text-lg font-semibold text-accent-fg shadow-glow hover:opacity-90 transition"
          >
            Analyze Your First Contract (Free)
          </Link>
        </div>
      </section>

      {/* Feature cards */}
      <section id="features" className="px-6 pb-24">
        <div className="mx-auto max-w-6xl">
          <h2 className="mb-10 text-center text-2xl font-semibold text-text-primary">
            Everything you need to review contracts with confidence
          </h2>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map(({ icon: Icon, title, description }) => (
              <div
                key={title}
                className="rounded-xl border border-subtle bg-card p-6 shadow-card hover:border-accent/40 transition"
              >
                <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-accent/10 text-accent">
                  <Icon size={20} />
                </div>
                <h3 className="mb-2 font-semibold text-text-primary">{title}</h3>
                <p className="text-small text-text-secondary leading-relaxed">{description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
