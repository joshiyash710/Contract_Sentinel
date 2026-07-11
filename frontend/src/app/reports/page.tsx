import type { ReactNode } from "react";
import { MoreHorizontal } from "lucide-react";
import { TopBar } from "@/components/shell/TopBar";
import { Card } from "@/components/ui/Card";
import { ScorePill } from "@/components/ui/ScorePill";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { BarChart } from "@/components/charts/BarChart";
import { AreaChart } from "@/components/charts/AreaChart";
import { DonutChart } from "@/components/charts/DonutChart";
import { Heatmap } from "@/components/charts/Heatmap";
import { GaugeChart } from "@/components/charts/GaugeChart";

// Sample data only (spec AC-20).
const RISK_BY_TYPE = [
  { name: "MSA", value: 30, secondary: 24 }, { name: "NDA", value: 42, secondary: 28 },
  { name: "SOW", value: 58, secondary: 30 }, { name: "Freelance", value: 44, secondary: 22 },
  { name: "PSA", value: 26, secondary: 32 }, { name: "Lease", value: 30, secondary: 20 },
  { name: "Vendor", value: 34, secondary: 24 }, { name: "Intl", value: 40, secondary: 22 },
];

const USAGE = [
  { name: "Jan", value: 8 }, { name: "Feb", value: 14 }, { name: "Mar", value: 11 },
  { name: "Apr", value: 18 }, { name: "May", value: 15 }, { name: "Jun", value: 22 },
];

const DISTRIBUTION = [
  { name: "High", value: 28, level: "high" as const },
  { name: "Amber", value: 34, level: "medium" as const },
  { name: "Low", value: 38, level: "low" as const },
];

const HEATMAP = [
  [0.2, 0.9, 0.8, 1.0, 0.7, 0.9, 0.6],
  [0.9, 0.5, 0.6, 0.4, 0.8, 0.5, 0.7],
  [1.0, 0.7, 0.5, 0.6, 0.4, 0.5, 0.3],
  [0.3, 0.6, 0.7, 0.5, 0.6, 0.4, 0.5],
  [0.2, 0.3, 0.4, 0.3, 0.5, 0.3, 0.2],
  [0.15, 0.2, 0.25, 0.2, 0.3, 0.2, 0.15],
  [0.2, 0.3, 0.2, 0.25, 0.2, 0.3, 0.2],
];
const HEAT_ROWS = ["Liability", "Property", "Key State", "IP", "Pox Nick", "Peg Elote", "Data"];
const HEAT_COLS = ["Sol", "Ref", "Pen", "Int", "Peg", "Pox", "Nck"];

const TOP_CLAUSES: { name: string; tone: "danger" | "warning" | "success"; label: string }[] = [
  { name: "Limitation of liability", tone: "danger", label: "High" },
  { name: "Intellectual property", tone: "warning", label: "Medium" },
  { name: "Freelancer agreement", tone: "danger", label: "High" },
  { name: "Indemnification", tone: "success", label: "Low" },
  { name: "Confidentiality", tone: "warning", label: "Medium" },
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

export default function ReportsPage() {
  return (
    <>
      <TopBar title="Risk Dashboard" userName="Sarah Jenkins" />
      <div className="p-6">
        <div className="grid grid-cols-12 gap-5">
          {/* Risk scores across contract types */}
          <Card className="col-span-12 xl:col-span-6">
            <CardHeader
              title="Risk Scores across Contract Types"
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
            <BarChart data={RISK_BY_TYPE} grouped height={220} />
          </Card>

          {/* Heatmap */}
          <Card className="col-span-12 xl:col-span-6">
            <CardHeader title="High-Risk Clauses by Category" />
            <div className="flex gap-3 overflow-x-auto">
              <div className="flex flex-col justify-around py-1 text-caption text-text-tertiary">
                {HEAT_ROWS.map((r) => (
                  <span key={r} className="h-[28px] leading-[28px]">{r}</span>
                ))}
              </div>
              <Heatmap data={HEATMAP} rowLabels={HEAT_ROWS} colLabels={HEAT_COLS} />
            </div>
          </Card>

          {/* Usage analytics (area) */}
          <Card className="col-span-12 md:col-span-6 xl:col-span-4">
            <CardHeader title="Usage Analytics" />
            <AreaChart data={USAGE} height={190} />
          </Card>

          {/* Total risk distribution (donut) */}
          <Card className="col-span-12 md:col-span-6 xl:col-span-4">
            <CardHeader title="Total Risk Distribution" />
            <div className="flex items-center gap-4">
              <div className="flex-1">
                <DonutChart data={DISTRIBUTION} height={190} />
              </div>
              <div className="flex flex-col gap-2.5">
                <Legend items={[{ color: "bg-risk-high", label: "High" }]} />
                <Legend items={[{ color: "bg-risk-medium", label: "Amber" }]} />
                <Legend items={[{ color: "bg-risk-low", label: "Low" }]} />
              </div>
            </div>
          </Card>

          {/* Top 5 risky clauses */}
          <Card className="col-span-12 xl:col-span-4">
            <CardHeader title="Top 5 Risky Clauses Detected" />
            <ol className="flex flex-col divide-y divide-subtle/50">
              {TOP_CLAUSES.map((c, i) => (
                <li key={c.name} className="flex items-center justify-between py-2.5">
                  <span className="flex items-center gap-3 text-body text-text-primary">
                    <span className="text-text-tertiary tabular-nums">{i + 1}.</span>
                    {c.name}
                  </span>
                  <StatusBadge label={c.label} tone={c.tone} />
                </li>
              ))}
            </ol>
          </Card>

          {/* Stat: total contracts */}
          <Card className="col-span-12 md:col-span-6 xl:col-span-4">
            <CardHeader title="Total Contracts Analyzed" />
            <div className="text-display font-extrabold text-text-primary tabular-nums">339</div>
            <p className="mt-1 text-small text-text-secondary">Across all workspaces</p>
          </Card>

          {/* Stat: portfolio health */}
          <Card className="col-span-12 md:col-span-6 xl:col-span-4">
            <CardHeader title="Overall Portfolio Health Score" />
            <div className="flex items-end gap-2">
              <span className="text-display font-extrabold text-risk-low tabular-nums">80%</span>
              <ScorePill value={80} className="mb-3" />
            </div>
            <p className="mt-1 text-small text-text-secondary">Healthy — low aggregate risk</p>
          </Card>

          {/* Gauge */}
          <Card className="col-span-12 xl:col-span-4">
            <CardHeader title="Portfolio Health Gauge" />
            <GaugeChart value={70} height={170} />
          </Card>
        </div>
      </div>
    </>
  );
}
