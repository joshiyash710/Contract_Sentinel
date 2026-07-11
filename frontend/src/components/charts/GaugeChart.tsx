"use client";

import { RadialBarChart, RadialBar, PolarAngleAxis, ResponsiveContainer } from "recharts";

/**
 * Radial 0–100 progress gauge ("Overall Portfolio Health Score", screen 3). spec AC-11 /
 * review B-3. The arc fill proportion reflects `value`; accent fill from tokens.
 */
export function GaugeChart({
  value,
  height = 180,
  label,
}: {
  value: number; // 0–100
  height?: number;
  label?: string;
}) {
  const pct = Math.max(0, Math.min(100, value));
  const data = [{ name: label ?? "score", value: pct, fill: "var(--accent)" }];
  return (
    <div style={{ width: "100%", height }} className="relative">
      <ResponsiveContainer width="100%" height="100%">
        <RadialBarChart
          data={data}
          startAngle={220}
          endAngle={-40}
          innerRadius="70%"
          outerRadius="100%"
        >
          <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
          <RadialBar dataKey="value" background cornerRadius={8} />
        </RadialBarChart>
      </ResponsiveContainer>
      <div className="absolute inset-0 flex items-center justify-center">
        <span data-testid="gauge-value" className="text-h2 font-bold text-text-primary tabular-nums">
          {pct}
        </span>
      </div>
    </div>
  );
}
