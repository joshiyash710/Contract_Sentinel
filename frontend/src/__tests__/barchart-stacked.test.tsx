import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BarChart, type StackSeries } from "@/components/charts/BarChart";

const STACK: StackSeries[] = [
  { key: "low", label: "Low", level: "low" },
  { key: "medium", label: "Medium", level: "medium" },
  { key: "high", label: "High", level: "high" },
];

describe("BarChart stacked mode (spec 018 D4)", () => {
  test("stacked_renders_one_series_per_stack_entry", () => {
    const data = [
      { name: "liability", low: 1, medium: 0, high: 2 },
      { name: "term", low: 4, medium: 0, high: 0 },
    ];
    const { container } = render(<BarChart data={data} stack={STACK} />);
    // Recharts renders one <g class="recharts-bar"> per <Bar>.
    expect(container.querySelectorAll(".recharts-bar").length).toBe(3);
  });

  test("legacy_value_series_unchanged", () => {
    const data = [{ name: "Jan", value: 8 }];
    const { container } = render(<BarChart data={data} />);
    expect(container.querySelectorAll(".recharts-bar").length).toBe(1);
  });

  test("empty_data_shows_no_data", () => {
    render(<BarChart data={[]} stack={STACK} />);
    expect(screen.getByTestId("chart-empty")).toBeInTheDocument();
  });
});
