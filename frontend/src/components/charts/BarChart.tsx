"use client";

import {
  BarChart as RBarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
} from "recharts";
import { chartTokens } from "@/lib/tokens";

export interface BarDatum {
  name: string;
  value: number;
  /** optional second series for the grouped variant (screen 3) */
  secondary?: number;
}

// Single + grouped/2-series variant (spec AC-11 / review B-3). Colors from tokens.
export function BarChart({
  data,
  grouped = false,
  height = 220,
}: {
  data: BarDatum[];
  grouped?: boolean;
  height?: number;
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
          <Bar dataKey="value" fill={chartTokens.bar1} radius={[3, 3, 0, 0]} />
          {grouped && <Bar dataKey="secondary" fill={chartTokens.bar2} radius={[3, 3, 0, 0]} />}
        </RBarChart>
      </ResponsiveContainer>
    </div>
  );
}
