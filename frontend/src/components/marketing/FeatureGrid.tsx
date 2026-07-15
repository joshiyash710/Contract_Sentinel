/**
 * Feature 019 — feature grid. The four primary cards plus a second row, each with a gradient
 * icon chip and a hover-lift. Anchored at #features (landing nav).
 */
import {
  PieChart,
  FileSearch,
  GitCompare,
  Plug,
  ShieldCheck,
  Zap,
  Scale,
  FileClock,
  type LucideIcon,
} from "lucide-react";

interface Feature {
  icon: LucideIcon;
  title: string;
  description: string;
}

const FEATURES: Feature[] = [
  {
    icon: PieChart,
    title: "Risk Scoring",
    description:
      "Every clause gets an AI-derived risk level — High, Medium, or Low — so you know exactly where to focus.",
  },
  {
    icon: FileSearch,
    title: "Clause-by-Clause Explanation",
    description:
      "Plain-English rationale for every flagged clause, backed by evidence from a legal knowledge base.",
  },
  {
    icon: GitCompare,
    title: "Contract Comparison",
    description:
      "Side-by-side redline suggestions generated automatically, ready for your counterparty.",
  },
  {
    icon: Plug,
    title: "Integration Ecosystem",
    description:
      "Push reports straight to Google Drive and notify stakeholders over Gmail in one click.",
  },
  {
    icon: ShieldCheck,
    title: "Evidence Trail",
    description:
      "Each finding cites the retrieved passages it relied on — auditable, never a black box.",
  },
  {
    icon: Zap,
    title: "Seconds, Not Hours",
    description:
      "A full review runs locally in about a minute, so you can triage a stack of contracts fast.",
  },
  {
    icon: Scale,
    title: "Self-Validating Findings",
    description:
      "A reflection pass discards weak flags before you ever see them, keeping the signal high.",
  },
  {
    icon: FileClock,
    title: "Durable History",
    description:
      "Every analysis is saved to your private workspace and survives restarts — pick up where you left off.",
  },
];

export function FeatureGrid() {
  return (
    <section id="features" className="px-6 py-24">
      <div className="mx-auto max-w-6xl">
        <div className="mx-auto mb-14 max-w-2xl text-center">
          <h2 className="text-3xl font-bold tracking-tight text-text-primary md:text-4xl">
            Everything you need to review contracts with confidence
          </h2>
          <p className="mt-4 text-body text-text-secondary">
            Purpose-built analysis, from first upload to a stakeholder-ready report.
          </p>
        </div>

        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map(({ icon: Icon, title, description }) => (
            <div
              key={title}
              className="group rounded-card border border-subtle bg-card p-6 shadow-lg shadow-black/20 transition duration-200 hover:-translate-y-1 hover:border-accent/50 hover:shadow-glow"
            >
              <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-accent-gradient text-accent-fg shadow-glow">
                <Icon size={20} />
              </div>
              <h3 className="mb-2 text-h3 font-semibold text-text-primary">{title}</h3>
              <p className="text-small leading-relaxed text-text-secondary">{description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
