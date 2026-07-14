"use client";

import {
  BarChart as RBarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
} from "recharts";
import { chartTokens, riskColor } from "@/lib/tokens";

export interface BarDatum {
  name: string;
  value?: number;
  /** optional second series for the grouped variant (screen 3) */
  secondary?: number;
  [key: string]: number | string | undefined; // extra numeric keys for the stacked variant
}

/** One stacked series (feature 018 D4): a data key + its risk level → token color. */
export interface StackSeries {
  key: string;
  label: string;
  level: "low" | "medium" | "high";
}

// Single + grouped (2-series) + stacked (N-series, feature 018) variant. Colors from tokens.
export function BarChart({
  data,
  grouped = false,
  height = 220,
  stack,
}: {
  data: BarDatum[];
  grouped?: boolean;
  height?: number;
  stack?: StackSeries[];
}) {
  if (!data || data.length === 0) {
    return <div data-testid="chart-empty" className="text-small text-text-tertiary">No data</div>;
  }
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <RBarChart data={data}>
          <XAxis dataKey="name" tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} axisLine={false} tickLine={false} />
          {stack && stack.length > 0 ? (
            // Stacked severity mode — one Bar per series; skip the default value/secondary bars.
            stack.map((s) => (
              <Bar key={s.key} stackId="a" dataKey={s.key} fill={riskColor(s.level)} radius={[0, 0, 0, 0]} />
            ))
          ) : (
            <>
              <Bar dataKey="value" fill={chartTokens.bar1} radius={[3, 3, 0, 0]} />
              {grouped && <Bar dataKey="secondary" fill={chartTokens.bar2} radius={[3, 3, 0, 0]} />}
            </>
          )}
        </RBarChart>
      </ResponsiveContainer>
    </div>
  );
}
