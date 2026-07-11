"use client";

import type { ReactNode } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer } from "recharts";
import { riskColor } from "@/lib/tokens";

export interface DonutSlice {
  name: string;
  value: number;
  /** risk level drives color; falls back to accent if omitted */
  level?: "low" | "medium" | "high";
}

export function DonutChart({
  data,
  height = 220,
  center,
}: {
  data: DonutSlice[];
  height?: number;
  center?: ReactNode;
}) {
  if (!data || data.length === 0) {
    return <div data-testid="chart-empty" className="text-small text-text-tertiary">No data</div>;
  }
  return (
    <div className="relative" style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            innerRadius="66%"
            outerRadius="90%"
            paddingAngle={2}
            stroke="none"
          >
            {data.map((d, i) => (
              <Cell key={i} fill={d.level ? riskColor(d.level) : "var(--accent)"} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      {center != null && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          {center}
        </div>
      )}
    </div>
  );
}
