"use client";

import Link from "next/link";
import {
  Plus,
  FileCheck2,
  ShieldCheck,
  TriangleAlert,
  Activity,
  ArrowUpRight,
} from "lucide-react";
import { useDashboard } from "@/lib/useDashboard";
import { useJobs } from "@/lib/useJobs";
import type { DashboardMetrics, JobListItem } from "@/lib/api/types";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { StatusBadge, type BadgeTone } from "@/components/ui/StatusBadge";
import { DonutChart, type DonutSlice } from "@/components/charts/DonutChart";
import { BarChart } from "@/components/charts/BarChart";
import { StatCard } from "./StatCard";

const BAND_LABEL: Record<string, string> = { healthy: "Healthy", elevated: "Elevated", at_risk: "At risk" };
const BAND_TONE: Record<string, BadgeTone> = { healthy: "success", elevated: "warning", at_risk: "danger" };
const BAND_ACCENT: Record<string, "high" | "medium" | "low"> = {
  healthy: "low",
  elevated: "medium",
  at_risk: "high",
};
const RISK_TONE: Record<string, BadgeTone> = { high: "danger", medium: "warning", low: "success", none: "neutral" };

export function DashboardView() {
  const { state, retry } = useDashboard();

  if (state.phase === "loading") return <Centered>Loading your dashboard…</Centered>;
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
  const slices: DonutSlice[] = (
    [
      { name: "High", value: m.risk_distribution.high, level: "high" },
      { name: "Medium", value: m.risk_distribution.medium, level: "medium" },
      { name: "Low", value: m.risk_distribution.low, level: "low" },
    ] as DonutSlice[]
  ).filter((s) => s.value > 0);

  return (
    <div className="p-6">
      {/* Hero header */}
      <div className="relative mb-6 overflow-hidden rounded-card border border-subtle bg-card-raised p-6">
        <div className="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full bg-accent-gradient opacity-10 blur-3xl" />
        <div className="relative flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-page-title text-text-primary">AI Command Center</h1>
            <p className="mt-1 text-body text-text-secondary">
              A live view of contract risk across your workspace.
            </p>
          </div>
          <Link href="/upload">
            <Button variant="primary" className="shrink-0">
              <Plus size={16} /> Upload New Contract
            </Button>
          </Link>
        </div>
      </div>

      {/* KPI row */}
      <div className="mb-5 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Contracts analyzed"
          value={m.completed_contracts}
          sub={`${m.total_contracts} total submitted`}
          icon={<FileCheck2 size={18} />}
          accent="accent"
        />
        <StatCard
          label="Portfolio health"
          value={`${m.portfolio_health_pct}%`}
          sub={
            <StatusBadge
              label={BAND_LABEL[m.portfolio_health_band] ?? m.portfolio_health_band}
              tone={BAND_TONE[m.portfolio_health_band] ?? "neutral"}
            />
          }
          icon={<ShieldCheck size={18} />}
          accent={BAND_ACCENT[m.portfolio_health_band] ?? "low"}
        />
        <StatCard
          label="Findings flagged"
          value={flagged}
          sub="across analyzed contracts"
          icon={<TriangleAlert size={18} />}
          accent="medium"
        />
        <StatCard
          label="High-risk clauses"
          value={m.risk_distribution.high}
          sub="need attention"
          icon={<Activity size={18} />}
          accent="high"
        />
      </div>

      <div className="grid grid-cols-12 gap-5">
        {/* Risk Summary */}
        <Card className="col-span-12 lg:col-span-5">
          <div className="mb-1 flex items-center justify-between">
            <h3 className="text-h3 font-semibold text-text-primary">Risk Summary</h3>
            <span className="text-small text-text-tertiary">All analyzed contracts</span>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <DonutChart
                data={slices}
                height={210}
                center={
                  <div className="text-center">
                    <div className="text-h1 font-bold text-text-primary tabular-nums">{flagged}</div>
                    <div className="text-small text-text-tertiary">findings</div>
                  </div>
                }
              />
            </div>
            <div className="flex flex-col gap-3 pr-2">
              <LegendDot color="bg-risk-high" label={`High: ${m.risk_distribution.high}`} />
              <LegendDot color="bg-risk-medium" label={`Med: ${m.risk_distribution.medium}`} />
              <LegendDot color="bg-risk-low" label={`Low: ${m.risk_distribution.low}`} />
            </div>
          </div>
        </Card>

        {/* Activity Feed */}
        <Card className="col-span-12 lg:col-span-7">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-h3 font-semibold text-text-primary">Recent Activity</h3>
            <span className="text-small text-text-tertiary">Latest analyses</span>
          </div>
          <ActivityFeed />
        </Card>

        {/* Usage Analytics */}
        <Card className="col-span-12">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-h3 font-semibold text-text-primary">Usage — last 30 days</h3>
            <span className="text-small text-text-tertiary">Contracts submitted per day</span>
          </div>
          <BarChart
            data={m.usage_timeline.map((b) => ({ name: b.period.slice(5), value: b.count }))}
            height={170}
          />
        </Card>
      </div>
    </div>
  );
}

function ActivityFeed() {
  const { state } = useJobs({ limit: 6 });
  if (state.phase === "loading")
    return <p className="py-8 text-center text-small text-text-tertiary">Loading…</p>;
  if (state.phase === "error")
    return <p className="py-8 text-center text-small text-text-tertiary">{state.message}</p>;
  if (state.phase === "empty" || !state.data?.items.length)
    return <p className="py-8 text-center text-small text-text-tertiary">No activity yet.</p>;

  return (
    <ul className="flex flex-col divide-y divide-subtle/60">
      {state.data.items.map((it) => (
        <ActivityRow key={it.job_id} item={it} />
      ))}
    </ul>
  );
}

function ActivityRow({ item }: { item: JobListItem }) {
  const when = (item.finished_at ?? item.submitted_at)?.replace("T", " ").slice(0, 16);
  const dot =
    item.status === "completed" && item.risk_band
      ? { high: "bg-risk-high", medium: "bg-risk-medium", low: "bg-risk-low", none: "bg-risk-low" }[
          item.risk_band
        ] ?? "bg-text-tertiary"
      : item.status === "failed"
        ? "bg-risk-high"
        : "bg-accent";
  const badge =
    item.status === "completed" && item.risk_band ? (
      <StatusBadge label={cap(item.risk_band)} tone={RISK_TONE[item.risk_band] ?? "neutral"} />
    ) : (
      <StatusBadge label={cap(item.status)} tone="neutral" />
    );

  const body = (
    <div className="flex items-center gap-3 py-3">
      <span className={`h-2.5 w-2.5 shrink-0 rounded-pill ${dot}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 truncate text-body font-medium text-text-primary">
          {item.original_filename}
          {item.status === "completed" && item.report_available && (
            <ArrowUpRight size={14} className="shrink-0 text-text-tertiary" />
          )}
        </div>
        <div className="text-small text-text-tertiary">{when}</div>
      </div>
      {badge}
    </div>
  );

  return item.status === "completed" && item.report_available ? (
    <li>
      <Link href={`/jobs/${item.job_id}/report`} className="block rounded-input px-1 hover:bg-card-raised">
        {body}
      </Link>
    </li>
  ) : (
    <li className="px-1">{body}</li>
  );
}

function EmptyState() {
  return (
    <Centered>
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-accent/15 text-accent">
        <FileCheck2 size={28} />
      </div>
      <h2 className="text-h2 font-bold">No contracts analyzed yet</h2>
      <p className="max-w-md text-body text-text-secondary">
        Upload your first contract to see your portfolio dashboard come to life.
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

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-2 text-body text-text-secondary">
      <span className={`h-2.5 w-2.5 rounded-pill ${color}`} />
      <span>{label}</span>
    </div>
  );
}

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
