/**
 * Chart-relevant token access (spec 013 §2.2 / plan §3.11).
 *
 * globals.css is the single source of truth for color. Recharts / the SVG heatmap need real
 * color STRINGS (not CSS `var(...)`), so at runtime we read the computed CSS variables off
 * the document root. For SSR and the jsdom test environment (where getComputedStyle returns
 * empty), we fall back to a static map — this is the ONE place besides globals.css where a
 * hex literal is permitted (the `no_hardcoded_hex` audit scans src/components only).
 */

const FALLBACK: Record<string, string> = {
  "--accent": "#7c6cf5",
  "--accent-gradient-from": "#7a5cff",
  "--accent-gradient-to": "#5b8def",
  "--risk-high": "#ef4444",
  "--risk-medium": "#f59e0b",
  "--risk-low": "#22c55e",
  "--chart-bar-1": "#7c6cf5",
  "--chart-bar-2": "#5b8def",
  "--heat-0": "#fef3c7",
  "--heat-1": "#fcd34d",
  "--heat-2": "#f59e0b",
  "--heat-3": "#f97316",
  "--heat-4": "#ef4444",
};

/** Resolve a single CSS custom property to a concrete color string. */
export function cssVar(name: string): string {
  if (typeof window !== "undefined" && typeof getComputedStyle === "function") {
    const val = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    if (val) return val;
  }
  return FALLBACK[name] ?? "";
}

/** Named accessors used by the chart wrappers. */
export const chartTokens = {
  get riskHigh() {
    return cssVar("--risk-high");
  },
  get riskMedium() {
    return cssVar("--risk-medium");
  },
  get riskLow() {
    return cssVar("--risk-low");
  },
  get bar1() {
    return cssVar("--chart-bar-1");
  },
  get bar2() {
    return cssVar("--chart-bar-2");
  },
  get accent() {
    return cssVar("--accent");
  },
  /** yellow → red ramp for the heatmap, low→high buckets. */
  get heatRamp() {
    return ["--heat-0", "--heat-1", "--heat-2", "--heat-3", "--heat-4"].map(cssVar);
  },
};

/** Risk-level → color, matching 001 RiskLevel. */
export function riskColor(level: "low" | "medium" | "high"): string {
  return cssVar(`--risk-${level}`);
}
