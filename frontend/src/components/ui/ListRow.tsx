import clsx from "clsx";
import type { ReactNode } from "react";

/**
 * Generic list row (Activity Feed + Notifications on screen 10; notification rows on screen
 * 11). Leading slot (icon/dot/avatar) + title/subtitle stack + optional trailing slot. Fully
 * props-driven — no baked strings (spec EC-5).
 */
export function ListRow({
  leading,
  title,
  subtitle,
  trailing,
  className,
}: {
  leading?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  trailing?: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("flex items-center gap-3 py-2.5", className)}>
      {leading != null && <div className="shrink-0">{leading}</div>}
      <div className="min-w-0 flex-1">
        <div className="text-body font-medium text-text-primary truncate">{title}</div>
        {subtitle != null && <div className="text-small text-text-secondary truncate">{subtitle}</div>}
      </div>
      {trailing != null && <div className="shrink-0">{trailing}</div>}
    </div>
  );
}
