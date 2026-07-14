"use client";

import Link from "next/link";
import {
  BarChart3,
  Grid3x3,
  TrendingUp,
  PieChart,
  ListOrdered,
  FileCheck2,
  ShieldCheck,
  Flame,
  Layers,
} from "lucide-react";
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
import { StatCard } from "./StatCard";

const STACK: StackSeries[] = [
  { key: "low", label: "Low", level: "low" },
  { key: "medium", label: "Medium", level: "medium" },
  { key: "high", label: "High", level: "high" },
];
const BAND_LABEL: Record<string, string> = { healthy: "Healthy", elevated: "Elevated", at_risk: "At risk" };
const BAND_TONE: Record<string, BadgeTone> = { healthy: "success", elevated: "warning", at_risk: "danger" };
const BAND_ACCENT: Record<string, "high" | "medium" | "low"> = { healthy: "low", elevated: "medium", at_risk: "high" };

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
  const flagged = m.risk_distribution.high + m.risk_distribution.medium + m.risk_distribution.low;
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
      {/* Hero */}
      <div className="relative mb-6 overflow-hidden rounded-card border border-subtle bg-card-raised p-6">
        <div className="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full bg-accent-gradient opacity-10 blur-3xl" />
        <div className="relative">
          <h1 className="text-page-title text-text-primary">Risk Dashboard</h1>
          <p className="mt-1 text-body text-text-secondary">
            Portfolio-wide clause risk, aggregated across every contract you&apos;ve analyzed.
          </p>
        </div>
      </div>

      {/* KPI band */}
      <div className="mb-5 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Contracts analyzed" value={m.completed_contracts}
          sub={`${m.total_contracts} total submitted`} icon={<FileCheck2 size={18} />} accent="accent" />
        <StatCard label="Findings flagged" value={flagged} sub="clauses reviewed"
          icon={<Flame size={18} />} accent="medium" />
        <StatCard label="High-risk clauses" value={m.risk_distribution.high} sub="need attention"
          icon={<ShieldCheck size={18} />} accent="high" />
        <StatCard label="Clause types tracked" value={m.risk_by_clause_type.length} sub="categories with findings"
          icon={<Layers size={18} />} accent="low" />
      </div>

      <div className="grid grid-cols-12 gap-5">
        {/* Risk by clause type (stacked) */}
        <Card className="col-span-12 xl:col-span-6">
          <CardHeader icon={<BarChart3 size={16} />} title="Risk by Clause Type"
            action={<Legend items={[
              { color: "bg-risk-high", label: "High" },
              { color: "bg-risk-medium", label: "Med" },
              { color: "bg-risk-low", label: "Low" },
            ]} />} />
          <BarChart data={barData} stack={STACK} height={220} />
        </Card>

        {/* Heatmap */}
        <Card className="col-span-12 xl:col-span-6">
          <CardHeader icon={<Grid3x3 size={16} />} title="High-Risk Clauses by Category" />
          <div className="flex gap-3 overflow-x-auto">
            <div className="flex flex-col justify-around py-1 text-caption text-text-tertiary">
              {m.clause_risk_heatmap.rows.map((r) => (
                <span key={r} className="h-[28px] leading-[28px]">{r}</span>
              ))}
            </div>
            <Heatmap data={m.clause_risk_heatmap.cells} rowLabels={m.clause_risk_heatmap.rows}
              colLabels={m.clause_risk_heatmap.cols} max={maxCell} />
          </div>
        </Card>

        {/* Usage */}
        <Card className="col-span-12 md:col-span-6 xl:col-span-4">
          <CardHeader icon={<TrendingUp size={16} />} title="Usage — last 30 days" />
          <AreaChart data={m.usage_timeline.map((b) => ({ name: b.period.slice(5), value: b.count }))} height={190} />
        </Card>

        {/* Distribution */}
        <Card className="col-span-12 md:col-span-6 xl:col-span-4">
          <CardHeader icon={<PieChart size={16} />} title="Total Risk Distribution" />
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <DonutChart data={slices} height={190} />
            </div>
            <div className="flex flex-col gap-2.5 text-small text-text-secondary">
              <LegendDot color="bg-risk-high" label={`High: ${m.risk_distribution.high}`} />
              <LegendDot color="bg-risk-medium" label={`Med: ${m.risk_distribution.medium}`} />
              <LegendDot color="bg-risk-low" label={`Low: ${m.risk_distribution.low}`} />
            </div>
          </div>
        </Card>

        {/* Top risky clauses */}
        <Card className="col-span-12 xl:col-span-4">
          <CardHeader icon={<ListOrdered size={16} />} title="Top Risky Clause Types" />
          {m.top_risky_clause_types.length === 0 ? (
            <p className="py-8 text-center text-small text-text-tertiary">None flagged yet.</p>
          ) : (
            <ol className="flex flex-col divide-y divide-subtle/60">
              {m.top_risky_clause_types.map((c, i) => (
                <li key={c.clause_type} className="flex items-center justify-between py-2.5">
                  <span className="flex items-center gap-3 text-body text-text-primary">
                    <span className="flex h-6 w-6 items-center justify-center rounded-pill bg-card-raised text-small tabular-nums text-text-tertiary">
                      {i + 1}
                    </span>
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
          <CardHeader icon={<FileCheck2 size={16} />} title="Total Contracts Analyzed" />
          <div className="text-display font-extrabold text-text-primary tabular-nums">
            {m.completed_contracts}
          </div>
          <p className="mt-1 text-small text-text-secondary">
            {m.total_contracts} total submission{m.total_contracts === 1 ? "" : "s"}
          </p>
        </Card>

        {/* Portfolio health gauge */}
        <Card className="col-span-12 md:col-span-6 xl:col-span-4" glow>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-h3 font-semibold text-text-primary">Portfolio Health</h3>
            <StatusBadge label={BAND_LABEL[m.portfolio_health_band] ?? m.portfolio_health_band}
              tone={BAND_TONE[m.portfolio_health_band] ?? "neutral"} />
          </div>
          <GaugeChart value={m.portfolio_health_pct} height={170} />
          <p className="mt-1 text-center text-small text-text-tertiary">
            {m.portfolio_health_pct}% — derived from aggregate clause risk
          </p>
        </Card>
      </div>
    </div>
  );
}

function CardHeader({ icon, title, action }: { icon?: React.ReactNode; title: string; action?: React.ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between">
      <h3 className="flex items-center gap-2 text-h3 font-semibold text-text-primary">
        {icon && <span className="text-text-tertiary">{icon}</span>}
        {title}
      </h3>
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

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-2">
      <span className={`h-2.5 w-2.5 rounded-pill ${color}`} />
      {label}
    </span>
  );
}

function EmptyState() {
  return (
    <Centered>
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-accent/15 text-accent">
        <BarChart3 size={28} />
      </div>
      <h2 className="text-h2 font-bold">No contracts analyzed yet</h2>
      <p className="max-w-md text-body text-text-secondary">
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
