import type { ReactNode } from "react";
import { Bell, Link2, MoreHorizontal, Plus, ArrowLeftRight } from "lucide-react";
import { TopBar } from "@/components/shell/TopBar";
import { SearchInput } from "@/components/ui/SearchInput";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ScorePill } from "@/components/ui/ScorePill";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { ListRow } from "@/components/ui/ListRow";
import { DonutChart } from "@/components/charts/DonutChart";
import { BarChart } from "@/components/charts/BarChart";
import type { RiskLevel } from "@/lib/api/types";

// Demo/sample data only — the shell layer renders no live contract data (spec AC-20).
const RISK_SLICES = [
  { name: "High", value: 8, level: "high" as const },
  { name: "Medium", value: 15, level: "medium" as const },
  { name: "Low", value: 22, level: "low" as const },
];

const ACTIVITY: { title: string; time: string; dot: string; level: RiskLevel }[] = [
  { title: "Recently analyzed contract", time: "Apr 13, 25 · 10:00", dot: "bg-accent", level: "high" },
  { title: "ContractSentinel A", time: "Apr 13, 25 · 10:00", dot: "bg-text-tertiary", level: "medium" },
  { title: "ContractSentinel B", time: "Apr 13, 25 · 10:00", dot: "bg-accent", level: "high" },
];

const USAGE = [
  { name: "T1", value: 60 }, { name: "T2", value: 95 }, { name: "T3", value: 45 },
  { name: "T4", value: 70 }, { name: "T5", value: 55 }, { name: "T6", value: 120 },
  { name: "T7", value: 80 }, { name: "T8", value: 65 },
];

function CardHeader({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between">
      <h3 className="text-h3 font-semibold text-text-primary">{title}</h3>
      {action ?? (
        <button className="text-text-tertiary hover:text-text-secondary" aria-label="More">
          <MoreHorizontal size={18} />
        </button>
      )}
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

export default function DashboardPage() {
  return (
    <>
      <TopBar search={<SearchInput />} userName="Sarah Jenkins" />
      <div className="p-6">
        {/* Page heading + primary action */}
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-page-title text-text-primary">AI Command Center</h1>
            <p className="mt-1 text-body text-text-secondary">
              Welcome back, Sarah Jenkins! Here is your latest contract overview.
            </p>
          </div>
          <Button variant="primary" className="shrink-0">
            <Plus size={16} /> Upload New Contract
          </Button>
        </div>

        <div className="grid grid-cols-12 gap-5">
          {/* Risk Summary */}
          <Card className="col-span-12 lg:col-span-5">
            <div className="mb-1 flex items-center justify-between">
              <h3 className="text-h3 font-semibold text-text-primary">Risk Summary</h3>
              <ScorePill value={78} />
            </div>
            <p className="mb-2 text-small text-text-secondary">Across all analyzed contracts</p>
            <div className="flex items-center gap-4">
              <div className="flex-1">
                <DonutChart
                  data={RISK_SLICES}
                  height={200}
                  center={
                    <div className="text-center">
                      <div className="text-h1 font-bold text-text-primary tabular-nums">78</div>
                      <div className="text-small text-text-tertiary">/100</div>
                    </div>
                  }
                />
              </div>
              <div className="flex flex-col gap-3 pr-2">
                <LegendDot color="bg-risk-high" label="High: 8" />
                <LegendDot color="bg-risk-medium" label="Med: 15" />
                <LegendDot color="bg-risk-low" label="Low: 22" />
              </div>
            </div>
          </Card>

          {/* Activity Feed */}
          <Card className="col-span-12 lg:col-span-4">
            <CardHeader title="Activity Feed" />
            <div className="divide-y divide-subtle/50">
              {ACTIVITY.map((a, i) => (
                <ListRow
                  key={i}
                  leading={<span className={`h-2.5 w-2.5 rounded-pill ${a.dot}`} />}
                  title={a.title}
                  subtitle={a.time}
                  trailing={<RiskBadge level={a.level} />}
                />
              ))}
            </div>
            <div className="mt-4 flex justify-center">
              <Button variant="secondary" className="px-6 py-1.5 text-small">
                Show more
              </Button>
            </div>
          </Card>

          {/* Right column: Notifications + Quick Actions */}
          <div className="col-span-12 flex flex-col gap-5 lg:col-span-3">
            <Card>
              <CardHeader title="Notifications" />
              <div className="flex flex-col gap-1">
                <ListRow
                  leading={
                    <span className="flex h-8 w-8 items-center justify-center rounded-pill bg-card-raised text-accent">
                      <Bell size={15} />
                    </span>
                  }
                  title="New report ready"
                  subtitle="Your latest report is ready."
                />
                <ListRow
                  leading={
                    <span className="flex h-8 w-8 items-center justify-center rounded-pill bg-card-raised text-accent">
                      <Link2 size={15} />
                    </span>
                  }
                  title="Integration connected"
                  subtitle="Google Drive connected."
                />
              </div>
            </Card>
            <Card>
              <CardHeader title="Quick Actions" />
              <p className="mb-4 text-small text-text-secondary">
                Upload and analyze a new contract.
              </p>
              <Button variant="primary" className="w-full">
                <Plus size={16} /> Upload New Contract
              </Button>
            </Card>
          </div>

          {/* Bottom-left wide Notifications */}
          <Card className="col-span-12 lg:col-span-8">
            <CardHeader title="Notifications" />
            <div className="flex flex-wrap gap-3">
              <Button variant="chip">
                <span className="h-2 w-2 rounded-pill bg-risk-high" /> New report ready
              </Button>
              <Button variant="chip">
                <ArrowLeftRight size={14} /> Sync integrations
              </Button>
            </div>
          </Card>

          {/* Bottom-right Usage Analytics */}
          <Card className="col-span-12 lg:col-span-4">
            <CardHeader title="Usage Analytics" />
            <BarChart data={USAGE} height={160} />
          </Card>
        </div>
      </div>
    </>
  );
}
