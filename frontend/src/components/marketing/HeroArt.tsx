"use client";

import { useRef } from "react";

const CLAUSES: { name: string; level: "high" | "medium" | "low"; label: string }[] = [
  { name: "Limitation of Liability", level: "high", label: "High" },
  { name: "Indemnification", level: "medium", label: "Medium" },
  { name: "Confidentiality", level: "low", label: "Low" },
];

const PILL: Record<string, string> = {
  high: "border-risk-high/40 bg-risk-high/10 text-risk-high shadow-[0_0_18px_-4px_var(--risk-high)]",
  medium:
    "border-risk-medium/40 bg-risk-medium/10 text-risk-medium shadow-[0_0_18px_-4px_var(--risk-medium)]",
  low: "border-risk-low/40 bg-risk-low/10 text-risk-low shadow-[0_0_18px_-4px_var(--risk-low)]",
};

/**
 * Feature 019 — hero artwork, refreshed to the 2026-08 design-refs: a glassmorphic product
 * mockup (window chrome titled MSA_AcmeCorp.pdf) presented on a 3D-tilted plane that reacts to
 * the pointer (parallax) — centered risk-score donut that draws itself in, then per-clause rows
 * (clause name left, glowing risk pill right), plus floating status chips. Purely decorative
 * (aria-hidden); token-driven colors.
 */
export function HeroArt() {
  const cardRef = useRef<HTMLDivElement>(null);

  // Pointer parallax: nudge the resting tilt toward the cursor, then ease back on leave.
  const handleMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const el = cardRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5; // -0.5 … 0.5
    const py = (e.clientY - r.top) / r.height - 0.5;
    el.style.setProperty("--ry", `${11 + px * 10}deg`);
    el.style.setProperty("--rx", `${5 - py * 10}deg`);
  };
  const handleLeave = () => {
    const el = cardRef.current;
    if (!el) return;
    el.style.removeProperty("--ry");
    el.style.removeProperty("--rx");
  };

  return (
    <div
      className="float-slow relative w-full"
      aria-hidden="true"
      onMouseMove={handleMove}
      onMouseLeave={handleLeave}
    >
      {/* Slowly rotating accent halo ring behind the window. */}
      <div className="pointer-events-none absolute left-1/2 top-1/2 h-[118%] w-[118%] -translate-x-1/2 -translate-y-1/2">
        <div className="accent-ring-conic spin-slow h-full w-full rounded-full opacity-50 blur-2xl" />
      </div>
      {/* Ambient glow that gently pulses. */}
      <div className="pointer-events-none absolute -inset-10 rounded-full bg-accent/15 blur-3xl [animation:halo_6s_ease-in-out_infinite]" />

      {/* The tilted glass window */}
      <div
        ref={cardRef}
        className="tilt-3d glass gloss relative overflow-hidden rounded-2xl shadow-[0_50px_120px_-30px_rgba(0,0,0,0.85)]"
      >
        {/* Window chrome — traffic lights, file name, and a "Redline ready" pill on the right */}
        <div className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
          <span className="h-3 w-3 rounded-full bg-risk-high/80" />
          <span className="h-3 w-3 rounded-full bg-risk-medium/80" />
          <span className="h-3 w-3 rounded-full bg-risk-low/80" />
          <span className="ml-3 text-small text-text-tertiary">MSA_AcmeCorp.pdf</span>
          <span className="ml-auto flex items-center gap-1.5 rounded-pill border border-white/10 bg-white/5 px-2.5 py-1 text-caption font-semibold text-text-secondary">
            <span className="h-1.5 w-1.5 rounded-full bg-accent [animation:dot-pulse_1.6s_ease-in-out_infinite]" />
            Redline ready
          </span>
        </div>

        {/* Centered risk-score donut */}
        <div className="flex justify-center px-7 pb-2 pt-8">
          <RiskDonut />
        </div>

        {/* Per-clause rows: name left, glowing pill right */}
        <div className="space-y-4 px-7 pb-10 pt-3">
          {CLAUSES.map(({ name, level, label }) => (
            <div key={name} className="flex items-center justify-between gap-4">
              <span className="text-body text-text-secondary">{name}</span>
              <span
                className={`inline-block shrink-0 rounded-pill border px-3.5 py-1 text-small font-medium ${PILL[level]}`}
              >
                {label}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Parsed toast — frosted glass like the main window, but dropped BELOW the window's
          bottom-left corner (over the dark page, not the clause text) so it reads as its own
          floating card instead of merging into the clause rows. */}
      <div className="glass gloss float-slow-2 absolute -bottom-9 -left-5 flex items-center gap-3 rounded-xl px-4 py-3 shadow-[0_24px_60px_-18px_rgba(0,0,0,0.9)]">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-risk-low/20 text-risk-low">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none">
            <path d="m5 12 5 5 9-11" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
        <div className="leading-tight">
          <div className="text-small font-semibold text-text-primary">11 clauses parsed</div>
          <div className="text-caption text-text-tertiary">in 12.4 seconds</div>
        </div>
      </div>
    </div>
  );
}

/** Risk-score ring: an accent-gradient arc (~78%) that draws itself in, over a track. */
function RiskDonut() {
  const r = 52;
  const c = 2 * Math.PI * r;
  const pct = 0.78;
  const arc = c * pct;
  return (
    <div className="relative shrink-0">
      {/* Soft glow behind the ring */}
      <div className="absolute inset-2 rounded-full bg-accent/20 blur-2xl [animation:halo_4s_ease-in-out_infinite]" />
      <svg viewBox="0 0 140 140" width="172" height="172" className="relative">
        <defs>
          <linearGradient id="heroDonut" x1="0" y1="1" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--accent-cyan)" />
            <stop offset="55%" stopColor="var(--accent-gradient-to)" />
            <stop offset="100%" stopColor="var(--accent-gradient-from)" />
          </linearGradient>
        </defs>
        <circle cx="70" cy="70" r={r} fill="none" stroke="var(--border-subtle)" strokeWidth="11" />
        <circle
          cx="70"
          cy="70"
          r={r}
          fill="none"
          stroke="url(#heroDonut)"
          strokeWidth="11"
          strokeLinecap="round"
          strokeDasharray={`${arc} ${c}`}
          transform="rotate(-90 70 70)"
          className="ring-draw"
          style={{ ["--c" as string]: `${arc}` } as React.CSSProperties}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-display text-4xl font-semibold text-text-primary">78</span>
        <span className="text-caption uppercase tracking-widest text-text-tertiary">Risk Score</span>
      </div>
    </div>
  );
}
