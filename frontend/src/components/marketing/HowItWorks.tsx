/**
 * Feature 019 — "How it works": a 3-step strip (Upload → AI analyzes → Get your report).
 * New vs. the reference mockups, so the landing reads like a real product page. Anchored #how.
 */
import { Upload, Cpu, FileCheck2, type LucideIcon } from "lucide-react";

interface Step {
  icon: LucideIcon;
  title: string;
  description: string;
}

const STEPS: Step[] = [
  {
    icon: Upload,
    title: "Upload your contract",
    description: "Drop in a PDF or DOCX. It goes straight to your private workspace.",
  },
  {
    icon: Cpu,
    title: "AI analyzes every clause",
    description:
      "The pipeline segments clauses, retrieves evidence, and scores risk — validating each finding.",
  },
  {
    icon: FileCheck2,
    title: "Get your report",
    description:
      "A clear, evidence-backed report with risk levels and redline suggestions, ready to share.",
  },
];

export function HowItWorks() {
  return (
    <section id="how" className="border-y border-subtle/60 bg-card/30 px-6 py-24">
      <div className="mx-auto max-w-6xl">
        <div className="mx-auto mb-14 max-w-2xl text-center">
          <h2 className="text-3xl font-bold tracking-tight text-text-primary md:text-4xl">
            How it works
          </h2>
          <p className="mt-4 text-body text-text-secondary">
            From upload to a stakeholder-ready report in three steps.
          </p>
        </div>

        <div className="grid gap-6 md:grid-cols-3">
          {STEPS.map(({ icon: Icon, title, description }, i) => (
            <div
              key={title}
              className="relative rounded-card border border-subtle bg-card p-7 shadow-lg shadow-black/20"
            >
              <div className="mb-5 flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-gradient text-accent-fg shadow-glow">
                  <Icon size={19} />
                </span>
                <span className="text-caption font-semibold uppercase tracking-widest text-text-tertiary">
                  Step {i + 1}
                </span>
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
