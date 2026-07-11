"use client";

import { PieChart, Pie, Cell, ResponsiveContainer } from "recharts";
import { riskColor } from "@/lib/tokens";

export interface DonutSlice {
  name: string;
  value: number;
  /** risk level drives color; falls back to accent if omitted */
  level?: "low" | "medium" | "high";
}

export function DonutChart({ data, height = 220 }: { data: DonutSlice[]; height?: number }) {
  if (!data || data.length === 0) {
    return <div data-testid="chart-empty" className="text-small text-text-tertiary">No data</div>;
  }
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius="60%" outerRadius="85%" stroke="none">
            {data.map((d, i) => (
              <Cell key={i} fill={d.level ? riskColor(d.level) : "var(--accent)"} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
