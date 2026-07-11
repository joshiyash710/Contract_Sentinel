"use client";

import { chartTokens } from "@/lib/tokens";

export interface HeatmapProps {
  /** row-major grid of values normalized 0–1 (or 0–100; see `max`). */
  data: number[][];
  rowLabels?: string[];
  colLabels?: string[];
  max?: number;
  cell?: number;
}

// Hand-rolled SVG grid, yellow→red ramp (High-Risk-Clauses heatmap, screen 3). Colors from
// tokens (chartTokens.heatRamp). spec AC-11.
export function Heatmap({ data, rowLabels, colLabels, max = 1, cell = 28 }: HeatmapProps) {
  if (!data || data.length === 0 || data[0].length === 0) {
    return <div data-testid="chart-empty" className="text-small text-text-tertiary">No data</div>;
  }
  const ramp = chartTokens.heatRamp;
  const bucket = (v: number) => {
    const n = Math.max(0, Math.min(1, v / max));
    return ramp[Math.min(ramp.length - 1, Math.floor(n * ramp.length))];
  };
  const rows = data.length;
  const cols = data[0].length;
  const gap = 3;
  const width = cols * (cell + gap);
  const height = rows * (cell + gap);

  return (
    <svg data-testid="heatmap" width={width} height={height} role="img" aria-label="Heatmap">
      {data.map((row, r) =>
        row.map((v, c) => (
          <rect
            key={`${r}-${c}`}
            x={c * (cell + gap)}
            y={r * (cell + gap)}
            width={cell}
            height={cell}
            rx={3}
            fill={bucket(v)}
          >
            {rowLabels && colLabels && <title>{`${rowLabels[r]} / ${colLabels[c]}: ${v}`}</title>}
          </rect>
        )),
      )}
    </svg>
  );
}
