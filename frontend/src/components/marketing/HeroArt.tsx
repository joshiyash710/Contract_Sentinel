/**
 * Feature 019 — hero artwork: a glowing shield + layered contract documents, recreated
 * with inline SVG so there is no external asset dependency. Purely decorative.
 */
export function HeroArt() {
  return (
    <div className="relative mx-auto aspect-square w-full max-w-md" aria-hidden="true">
      {/* Ambient glow behind the artwork */}
      <div className="absolute inset-0 rounded-full bg-accent/20 blur-3xl" />

      <svg
        viewBox="0 0 400 400"
        className="relative h-full w-full drop-shadow-[0_20px_60px_rgba(124,108,245,0.35)]"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <linearGradient id="shieldGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="var(--accent-gradient-from)" />
            <stop offset="100%" stopColor="var(--accent-gradient-to)" />
          </linearGradient>
          <linearGradient id="paperGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--bg-card-raised)" />
            <stop offset="100%" stopColor="var(--bg-card)" />
          </linearGradient>
        </defs>

        {/* Back document */}
        <g transform="rotate(-9 150 210)">
          <rect x="66" y="96" width="168" height="220" rx="14" fill="url(#paperGrad)"
                stroke="var(--border-subtle)" strokeWidth="2" />
          <rect x="92" y="132" width="116" height="9" rx="4.5" fill="var(--border-subtle)" />
          <rect x="92" y="158" width="90" height="9" rx="4.5" fill="var(--border-subtle)" />
          <rect x="92" y="184" width="116" height="9" rx="4.5" fill="var(--border-subtle)" />
          <rect x="92" y="210" width="70" height="9" rx="4.5" fill="var(--border-subtle)" />
        </g>

        {/* Front document */}
        <g transform="rotate(7 250 200)">
          <rect x="180" y="70" width="176" height="232" rx="14" fill="url(#paperGrad)"
                stroke="var(--border-subtle)" strokeWidth="2" />
          <rect x="206" y="104" width="124" height="9" rx="4.5" fill="var(--accent)" opacity="0.55" />
          <rect x="206" y="130" width="96" height="9" rx="4.5" fill="var(--border-subtle)" />
          <rect x="206" y="156" width="124" height="9" rx="4.5" fill="var(--border-subtle)" />
          <rect x="206" y="182" width="80" height="9" rx="4.5" fill="var(--border-subtle)" />
          <rect x="206" y="240" width="124" height="9" rx="4.5" fill="var(--border-subtle)" />
          <rect x="206" y="266" width="60" height="9" rx="4.5" fill="var(--border-subtle)" />
        </g>

        {/* Shield */}
        <g transform="translate(200 210)">
          <path
            d="M0 -96 L84 -60 V4 C84 62 46 104 0 124 C-46 104 -84 62 -84 4 V-60 Z"
            fill="url(#shieldGrad)"
            stroke="var(--accent-fg)"
            strokeOpacity="0.25"
            strokeWidth="2"
          />
          <path
            d="M-34 4 L-8 32 L40 -26"
            fill="none"
            stroke="var(--accent-fg)"
            strokeWidth="12"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>

        {/* Sparkles */}
        <path d="M330 60 l6 14 14 6 -14 6 -6 14 -6 -14 -14 -6 14 -6 z"
              fill="var(--accent)" opacity="0.7" />
        <path d="M70 300 l4 10 10 4 -10 4 -4 10 -4 -10 -10 -4 10 -4 z"
              fill="var(--accent-gradient-to)" opacity="0.6" />
      </svg>
    </div>
  );
}
