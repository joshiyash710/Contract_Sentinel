"use client";

import clsx from "clsx";

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  "aria-label"?: string;
  className?: string;
}

export function Toggle({ checked, onChange, className, ...aria }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={aria["aria-label"]}
      onClick={() => onChange(!checked)}
      className={clsx(
        "relative inline-flex h-6 w-11 items-center rounded-pill transition",
        checked ? "bg-accent" : "bg-card-raised border border-subtle",
        className,
      )}
    >
      <span
        className={clsx(
          "inline-block h-4 w-4 rounded-pill bg-white transition-transform",
          checked ? "translate-x-6" : "translate-x-1",
        )}
      />
    </button>
  );
}
