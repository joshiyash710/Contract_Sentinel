"use client";

import Link from "next/link";
import { useDashboard } from "@/lib/useDashboard";
import type { DashboardMetrics } from "@/lib/api/types";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { StatusBadge, type BadgeTone } from "@/components/ui/StatusBadge";
import { BarChart, type StackSeries } from "@/components/charts/BarChart";
import { AreaChart } from "@/components/charts/AreaChart";
import { DonutChart, type DonutSlice } from "@/components/charts/DonutChart";
import { Heatmap } from "@/components/charts/Heatmap";
import { GaugeChart } from "@/components/charts/GaugeChart";

const STACK: StackSeries[] = [
  { key: "low", label: "Low", level: "low" },
  { key: "medium", label: "Medium", level: "medium" },
  { key: "high", label: "High", level: "high" },
];
const BAND_LABEL: Record<string, string> = { healthy: "Healthy", elevated: "Elevated", at_risk: "At risk" };
const BAND_TONE: Record<string, BadgeTone> = { healthy: "success", elevated: "warning", at_risk: "danger" };

export function ReportsView() {
  const { state, retry } = useDashboard();

  if (state.phase === "loading") return <Centered>Loading your risk dashboard…</Centered>;
  if (state.phase === "error")
    return (
      <Centered>
        <p className="text-text-secondary">{state.message}</p>
        <Button variant="primary" onClick={retry}>
          Try again
        </Button>
      </Centered>
    );
  if (state.phase === "empty") return <EmptyState />;

  const m = state.data as DashboardMetrics;
  const barData = m.risk_by_clause_type.map((t) => ({
    name: t.clause_type,
    low: t.low,
    medium: t.medium,
    high: t.high,
  }));
  const maxCell = Math.max(1, ...m.clause_risk_heatmap.cells.flat());
  const slices: DonutSlice[] = (
    [
      { name: "High", value: m.risk_distribution.high, level: "high" },
      { name: "Medium", value: m.risk_distribution.medium, level: "medium" },
      { name: "Low", value: m.risk_distribution.low, level: "low" },
    ] as DonutSlice[]
  ).filter((s) => s.value > 0);

  return (
    <div className="p-6">
      <div className="grid grid-cols-12 gap-5">
        {/* Risk by clause type (stacked) */}
        <Card className="col-span-12 xl:col-span-6">
          <CardHeader
            title="Risk by Clause Type"
            action={
              <Legend
                items={[
                  { color: "bg-risk-high", label: "High" },
                  { color: "bg-risk-medium", label: "Med" },
                  { color: "bg-risk-low", label: "Low" },
                ]}
              />
            }
          />
          <BarChart data={barData} stack={STACK} height={220} />
        </Card>

        {/* Heatmap: clause_type × severity */}
        <Card className="col-span-12 xl:col-span-6">
          <CardHeader title="High-Risk Clauses by Category" />
          <div className="flex gap-3 overflow-x-auto">
            <div className="flex flex-col justify-around py-1 text-caption text-text-tertiary">
              {m.clause_risk_heatmap.rows.map((r) => (
                <span key={r} className="h-[28px] leading-[28px]">
                  {r}
                </span>
              ))}
            </div>
            <Heatmap
              data={m.clause_risk_heatmap.cells}
              rowLabels={m.clause_risk_heatmap.rows}
              colLabels={m.clause_risk_heatmap.cols}
              max={maxCell}
            />
          </div>
        </Card>

        {/* Usage */}
        <Card className="col-span-12 md:col-span-6 xl:col-span-4">
          <CardHeader title="Usage Analytics" />
          <AreaChart
            data={m.usage_timeline.map((b) => ({ name: b.period.slice(5), value: b.count }))}
            height={190}
          />
        </Card>

        {/* Total risk distribution */}
        <Card className="col-span-12 md:col-span-6 xl:col-span-4">
          <CardHeader title="Total Risk Distribution" />
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <DonutChart data={slices} height={190} />
            </div>
            <div className="flex flex-col gap-2.5 text-small text-text-secondary">
              <span>High: {m.risk_distribution.high}</span>
              <span>Med: {m.risk_distribution.medium}</span>
              <span>Low: {m.risk_distribution.low}</span>
            </div>
          </div>
        </Card>

        {/* Top risky clauses */}
        <Card className="col-span-12 xl:col-span-4">
          <CardHeader title="Top Risky Clause Types" />
          {m.top_risky_clause_types.length === 0 ? (
            <p className="py-6 text-center text-small text-text-tertiary">None flagged yet.</p>
          ) : (
            <ol className="flex flex-col divide-y divide-subtle/50">
              {m.top_risky_clause_types.map((c, i) => (
                <li key={c.clause_type} className="flex items-center justify-between py-2.5">
                  <span className="flex items-center gap-3 text-body text-text-primary">
                    <span className="text-text-tertiary tabular-nums">{i + 1}.</span>
                    {c.clause_type}
                  </span>
                  <StatusBadge label={`${c.high_count} high`} tone="danger" />
                </li>
              ))}
            </ol>
          )}
        </Card>

        {/* Total contracts */}
        <Card className="col-span-12 md:col-span-6 xl:col-span-4">
          <CardHeader title="Total Contracts Analyzed" />
          <div className="text-display font-extrabold text-text-primary tabular-nums">
            {m.completed_contracts}
          </div>
          <p className="mt-1 text-small text-text-secondary">
            {m.total_contracts} total submission{m.total_contracts === 1 ? "" : "s"}
          </p>
        </Card>

        {/* Portfolio health gauge */}
        <Card className="col-span-12 md:col-span-6 xl:col-span-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-h3 font-semibold text-text-primary">Portfolio Health</h3>
            <StatusBadge
              label={BAND_LABEL[m.portfolio_health_band] ?? m.portfolio_health_band}
              tone={BAND_TONE[m.portfolio_health_band] ?? "neutral"}
            />
          </div>
          <GaugeChart value={m.portfolio_health_pct} height={170} />
        </Card>
      </div>
    </div>
  );
}

function CardHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between">
      <h3 className="text-h3 font-semibold text-text-primary">{title}</h3>
      {action}
    </div>
  );
}

function Legend({ items }: { items: { color: string; label: string }[] }) {
  return (
    <div className="flex items-center gap-3">
      {items.map((it) => (
        <span key={it.label} className="flex items-center gap-1.5 text-small text-text-secondary">
          <span className={`h-2.5 w-2.5 rounded-pill ${it.color}`} />
          {it.label}
        </span>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <Centered>
      <h2 className="text-h2 font-bold">No contracts analyzed yet</h2>
      <p className="text-body text-text-secondary">
        Your risk dashboard fills in once you&apos;ve analyzed some contracts.
      </p>
      <Link href="/upload" className="text-accent font-medium hover:underline">
        Upload a contract
      </Link>
    </Centered>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-6 text-center">
      {children}
    </div>
  );
}
