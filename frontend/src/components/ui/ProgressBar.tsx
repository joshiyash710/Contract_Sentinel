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
      className={clsx(
        "h-2.5 w-full overflow-hidden rounded-pill border border-white/5 bg-white/5",
        className,
      )}
    >
      <div
        className="relative h-full overflow-hidden rounded-pill bg-accent-gradient shadow-[0_0_16px_-2px_var(--accent)] transition-[width] duration-700 ease-out"
        style={{ width: `${pct}%` }}
      >
        {/* top gloss highlight */}
        <div className="absolute inset-x-0 top-0 h-1/2 rounded-pill bg-white/25" />
        {/* travelling gloss sweep */}
        <div className="absolute inset-y-0 w-1/3 bg-white/30 blur-sm [animation:bar-gloss_1.8s_var(--ease-expo)_infinite]" />
      </div>
    </div>
  );
}
