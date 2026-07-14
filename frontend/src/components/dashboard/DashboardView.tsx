"use client";

import Link from "next/link";
import { Plus } from "lucide-react";
import { useDashboard } from "@/lib/useDashboard";
import { useJobs } from "@/lib/useJobs";
import type { DashboardMetrics, JobListItem } from "@/lib/api/types";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ListRow } from "@/components/ui/ListRow";
import { StatusBadge, type BadgeTone } from "@/components/ui/StatusBadge";
import { DonutChart, type DonutSlice } from "@/components/charts/DonutChart";
import { BarChart } from "@/components/charts/BarChart";

const BAND_LABEL: Record<string, string> = {
  healthy: "Healthy",
  elevated: "Elevated",
  at_risk: "At risk",
};
const BAND_TONE: Record<string, BadgeTone> = {
  healthy: "success",
  elevated: "warning",
  at_risk: "danger",
};
const RISK_TONE: Record<string, BadgeTone> = {
  high: "danger",
  medium: "warning",
  low: "success",
  none: "neutral",
};

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
  const slices: DonutSlice[] = (
    [
      { name: "High", value: m.risk_distribution.high, level: "high" },
      { name: "Medium", value: m.risk_distribution.medium, level: "medium" },
      { name: "Low", value: m.risk_distribution.low, level: "low" },
    ] as DonutSlice[]
  ).filter((s) => s.value > 0);

  return (
    <div className="p-6">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-page-title text-text-primary">AI Command Center</h1>
          <p className="mt-1 text-body text-text-secondary">
            {m.completed_contracts} contract{m.completed_contracts === 1 ? "" : "s"} analyzed
            across your workspace.
          </p>
        </div>
        <Link href="/upload">
          <Button variant="primary" className="shrink-0">
            <Plus size={16} /> Upload New Contract
          </Button>
        </Link>
      </div>

      <div className="grid grid-cols-12 gap-5">
        {/* Risk Summary */}
        <Card className="col-span-12 lg:col-span-5">
          <div className="mb-1 flex items-center justify-between">
            <h3 className="text-h3 font-semibold text-text-primary">Risk Summary</h3>
            <StatusBadge
              label={`${m.portfolio_health_pct}% · ${BAND_LABEL[m.portfolio_health_band] ?? m.portfolio_health_band}`}
              tone={BAND_TONE[m.portfolio_health_band] ?? "neutral"}
            />
          </div>
          <p className="mb-2 text-small text-text-secondary">Across all analyzed contracts</p>
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <DonutChart
                data={slices}
                height={200}
                center={
                  <div className="text-center">
                    <div className="text-h1 font-bold text-text-primary tabular-nums">
                      {m.completed_contracts}
                    </div>
                    <div className="text-small text-text-tertiary">analyzed</div>
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
        <Card className="col-span-12 lg:col-span-4">
          <h3 className="mb-2 text-h3 font-semibold text-text-primary">Activity Feed</h3>
          <ActivityFeed />
        </Card>

        {/* Quick actions (static chrome — D12) */}
        <div className="col-span-12 flex flex-col gap-5 lg:col-span-3">
          <Card>
            <h3 className="mb-2 text-h3 font-semibold text-text-primary">Quick Actions</h3>
            <p className="mb-4 text-small text-text-secondary">Upload and analyze a new contract.</p>
            <Link href="/upload">
              <Button variant="primary" className="w-full">
                <Plus size={16} /> Upload New Contract
              </Button>
            </Link>
          </Card>
        </div>

        {/* Usage Analytics */}
        <Card className="col-span-12 lg:col-span-8">
          <h3 className="mb-2 text-h3 font-semibold text-text-primary">Usage Analytics</h3>
          <BarChart
            data={m.usage_timeline.map((b) => ({ name: b.period.slice(5), value: b.count }))}
            height={160}
          />
        </Card>
      </div>
    </div>
  );
}

function ActivityFeed() {
  const { state } = useJobs({ limit: 6 });
  if (state.phase === "loading")
    return <p className="py-6 text-center text-small text-text-tertiary">Loading…</p>;
  if (state.phase === "error")
    return <p className="py-6 text-center text-small text-text-tertiary">{state.message}</p>;
  if (state.phase === "empty" || !state.data?.items.length)
    return (
      <p className="py-6 text-center text-small text-text-tertiary">No activity yet.</p>
    );

  return (
    <div className="divide-y divide-subtle/50">
      {state.data.items.map((it) => (
        <ActivityRow key={it.job_id} item={it} />
      ))}
    </div>
  );
}

function ActivityRow({ item }: { item: JobListItem }) {
  const when = (item.finished_at ?? item.submitted_at)?.replace("T", " ").slice(0, 16);
  const badge =
    item.status === "completed" && item.risk_band ? (
      <StatusBadge label={cap(item.risk_band)} tone={RISK_TONE[item.risk_band] ?? "neutral"} />
    ) : (
      <StatusBadge label={cap(item.status)} tone="neutral" />
    );
  const row = (
    <ListRow
      leading={<span className="h-2.5 w-2.5 rounded-pill bg-accent" />}
      title={item.original_filename}
      subtitle={when}
      trailing={badge}
    />
  );
  return item.status === "completed" && item.report_available ? (
    <Link href={`/jobs/${item.job_id}/report`} className="block hover:bg-card-raised">
      {row}
    </Link>
  ) : (
    row
  );
}

function EmptyState() {
  return (
    <Centered>
      <h2 className="text-h2 font-bold">No contracts analyzed yet</h2>
      <p className="text-body text-text-secondary">
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
