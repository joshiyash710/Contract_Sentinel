import clsx from "clsx";

/**
 * Discrete labeled step header ("1 Upload · 2 AI Analysis · 3 Review", screen 9). Exactly one
 * "current" step; past/future styled distinctly (spec AC-10). Distinct from the continuous
 * ProgressBar.
 */
export function Stepper({
  steps,
  current,
  className,
}: {
  steps: string[];
  current: number; // 0-indexed
  className?: string;
}) {
  return (
    <ol className={clsx("flex items-center gap-4", className)}>
      {steps.map((label, i) => {
        const state = i < current ? "past" : i === current ? "current" : "future";
        return (
          <li key={label} data-state={state} className="flex items-center gap-2">
            <span
              className={clsx(
                "flex h-6 w-6 items-center justify-center rounded-pill text-small font-semibold",
                state === "current" && "bg-accent-gradient text-accent-fg",
                state === "past" && "bg-accent/20 text-accent",
                state === "future" && "bg-card-raised text-text-tertiary",
              )}
            >
              {i + 1}
            </span>
            <span
              className={clsx(
                "text-body",
                state === "current" ? "text-text-primary font-medium" : "text-text-secondary",
              )}
            >
              {label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
