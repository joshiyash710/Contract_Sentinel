import clsx from "clsx";

/**
 * Determinate horizontal progress bar (Processing screen 6, Clause-doc panel screen 5).
 * Distinct from the discrete Stepper. 015/016 wire `value` to SSE index/total (011 §2.4).
 */
export function ProgressBar({
  value,
  className,
}: {
  value: number; // 0–100
  className?: string;
}) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      className={clsx("h-1.5 w-full rounded-pill bg-card-raised overflow-hidden", className)}
    >
      <div className="h-full rounded-pill bg-accent-gradient transition-all" style={{ width: `${pct}%` }} />
    </div>
  );
}
