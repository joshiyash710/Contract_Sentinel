"use client";

import {
  AreaChart as RAreaChart,
  Area,
  XAxis,
  YAxis,
  ResponsiveContainer,
} from "recharts";

export interface AreaDatum {
  name: string;
  value: number;
}

// Violet gradient area (Usage Analytics, screen 3). Gradient stops read the CSS vars.
export function AreaChart({ data, height = 220 }: { data: AreaDatum[]; height?: number }) {
  if (!data || data.length === 0) {
    return <div data-testid="chart-empty" className="text-small text-text-tertiary">No data</div>;
  }
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <RAreaChart data={data}>
          <defs>
            <linearGradient id="cs-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--chart-area-from)" />
              <stop offset="100%" stopColor="var(--chart-area-to)" />
            </linearGradient>
          </defs>
          <XAxis dataKey="name" tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} axisLine={false} tickLine={false} />
          <Area type="monotone" dataKey="value" stroke="var(--accent)" strokeWidth={2} fill="url(#cs-area)" />
        </RAreaChart>
      </ResponsiveContainer>
    </div>
  );
}
