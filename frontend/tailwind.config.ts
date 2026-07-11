import type { Config } from "tailwindcss";

// The theme REFERENCES the CSS custom properties defined in src/app/globals.css so that
// Tailwind utilities and raw CSS resolve to the SAME hex — globals.css is the single source
// of truth for color (spec AC-1). No hex literal appears in this file.
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        app: "var(--bg-app)",
        sidebar: "var(--bg-sidebar)",
        card: "var(--bg-card)",
        "card-raised": "var(--bg-card-raised)",
        subtle: "var(--border-subtle)",
        accent: "var(--accent)",
        "accent-fg": "var(--accent-fg)",
        "border-focus": "var(--border-focus)",
        "risk-high": "var(--risk-high)",
        "risk-medium": "var(--risk-medium)",
        "risk-low": "var(--risk-low)",
        "text-primary": "var(--text-primary)",
        "text-secondary": "var(--text-secondary)",
        "text-tertiary": "var(--text-tertiary)",
      },
      borderRadius: {
        card: "var(--radius-card)",
        input: "var(--radius-input)",
        pill: "var(--radius-pill)",
      },
      backgroundImage: {
        "accent-gradient":
          "linear-gradient(90deg, var(--accent-gradient-from), var(--accent-gradient-to))",
      },
      boxShadow: { glow: "var(--glow-accent)" },
      fontFamily: { sans: ["var(--font-inter)", "system-ui", "sans-serif"] },
      fontSize: {
        display: ["3.5rem", { lineHeight: "1.05", fontWeight: "800", letterSpacing: "-0.02em" }],
        "page-title": ["2.375rem", { lineHeight: "1.1", fontWeight: "700", letterSpacing: "-0.01em" }],
        h1: ["2rem", { lineHeight: "1.15", fontWeight: "700" }],
        h2: ["1.5rem", { lineHeight: "1.2", fontWeight: "700" }],
        h3: ["1.125rem", { lineHeight: "1.3", fontWeight: "600" }],
        body: ["0.9375rem", { lineHeight: "1.5" }],
        small: ["0.8125rem", { lineHeight: "1.4" }],
        caption: ["0.6875rem", { lineHeight: "1.3" }],
      },
    },
  },
  plugins: [],
};

export default config;
