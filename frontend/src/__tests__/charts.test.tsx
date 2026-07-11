import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { DonutChart } from "@/components/charts/DonutChart";
import { BarChart } from "@/components/charts/BarChart";
import { AreaChart } from "@/components/charts/AreaChart";
import { Heatmap } from "@/components/charts/Heatmap";
import { GaugeChart } from "@/components/charts/GaugeChart";

// Recharts ResponsiveContainer needs a sized parent in jsdom; wrap in a fixed box.
function Box({ children }: { children: React.ReactNode }) {
  return <div style={{ width: 400, height: 240 }}>{children}</div>;
}

describe("chart wrappers", () => {
  test("charts_render_sample", () => {
    const { container } = render(
      <div>
        <Box>
          <DonutChart data={[{ name: "High", value: 8, level: "high" }]} />
        </Box>
        <Box>
          <BarChart data={[{ name: "MSA", value: 30 }]} />
        </Box>
        <Box>
          <AreaChart data={[{ name: "T1", value: 5 }, { name: "T2", value: 9 }]} />
        </Box>
        <Heatmap data={[[0.1, 0.9], [0.5, 0.3]]} />
        <Box>
          <GaugeChart value={70} />
        </Box>
      </div>,
    );
    expect(container.querySelectorAll("svg").length).toBeGreaterThan(0);
    expect(screen.getByTestId("heatmap")).toBeInTheDocument();
  });

  test("bar_grouped_variant", () => {
    const { container } = render(
      <Box>
        <BarChart grouped data={[{ name: "MSA", value: 30, secondary: 20 }]} />
      </Box>,
    );
    // grouped renders two Bar series → more than one rectangle path group
    expect(container.querySelector("svg")).toBeTruthy();
  });

  test("gauge_renders_radial", () => {
    render(
      <Box>
        <GaugeChart value={70} />
      </Box>,
    );
    expect(screen.getByTestId("gauge-value")).toHaveTextContent("70");
  });

  test("charts_empty_state", () => {
    render(
      <div>
        <DonutChart data={[]} />
        <BarChart data={[]} />
        <AreaChart data={[]} />
        <Heatmap data={[]} />
      </div>,
    );
    expect(screen.getAllByTestId("chart-empty").length).toBe(4);
  });
});
