/**
 * Feature 019 — left brand panel for the split auth layout (wide screens only). Aurora
 * backdrop, logo, one-line value prop, and a subtle proof point. Purely decorative.
 */
import { ShieldCheck, Sparkles, FileCheck2 } from "lucide-react";

export function AuthBrandPanel() {
  return (
    <div className="bg-aurora relative hidden flex-col justify-between border-r border-subtle p-12 md:flex">
      <div className="flex items-center gap-2.5">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-gradient text-accent-fg font-bold shadow-glow">
          C
        </span>
        <span className="text-h3 font-semibold tracking-tight text-text-primary">
          ContractSentinel
        </span>
      </div>

      <div className="max-w-md">
        <h2 className="text-3xl font-bold leading-tight tracking-tight text-text-primary">
          Understand every contract{" "}
          <span className="bg-accent-gradient bg-clip-text text-transparent">before you sign.</span>
        </h2>
        <p className="mt-4 text-body leading-relaxed text-text-secondary">
          Risk scoring, clause-by-clause explanations, and redline suggestions — in your own
          private workspace.
        </p>

        <ul className="mt-8 space-y-3.5">
          {[
            { icon: ShieldCheck, text: "Every finding is evidence-backed" },
            { icon: Sparkles, text: "AI risk scoring on every clause" },
            { icon: FileCheck2, text: "Stakeholder-ready reports in minutes" },
          ].map(({ icon: Icon, text }) => (
            <li key={text} className="flex items-center gap-3 text-body text-text-secondary">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-card-raised/70 text-accent backdrop-blur">
                <Icon size={16} />
              </span>
              {text}
            </li>
          ))}
        </ul>
      </div>

      <p className="text-small text-text-tertiary">Private by design · Runs on your machine</p>
    </div>
  );
}
