"use client";

import clsx from "clsx";

export type TabsVariant = "segmented" | "underline";

export interface TabItem {
  value: string;
  label: string;
}

interface TabsProps {
  items: TabItem[];
  value: string;
  onChange: (value: string) => void;
  variant?: TabsVariant;
  className?: string;
}

// Two variants (spec AC-8): segmented pill (Login/Sign-Up, screen 2) and underline
// (Profile/Billing/…, screen 4; Chat/Active, screen 7).
export function Tabs({ items, value, onChange, variant = "segmented", className }: TabsProps) {
  if (variant === "segmented") {
    return (
      <div
        role="tablist"
        className={clsx("inline-flex rounded-input bg-card-raised p-1 border border-subtle", className)}
      >
        {items.map((it) => {
          const active = it.value === value;
          return (
            <button
              key={it.value}
              role="tab"
              aria-selected={active}
              onClick={() => onChange(it.value)}
              className={clsx(
                "rounded-input px-4 py-1.5 text-body font-medium transition",
                active ? "bg-card text-text-primary shadow-glow" : "text-text-secondary",
              )}
            >
              {it.label}
            </button>
          );
        })}
      </div>
    );
  }
  // underline
  return (
    <div role="tablist" className={clsx("flex gap-6 border-b border-subtle", className)}>
      {items.map((it) => {
        const active = it.value === value;
        return (
          <button
            key={it.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(it.value)}
            className={clsx(
              "-mb-px border-b-2 px-1 py-2.5 text-body font-medium transition",
              active
                ? "border-accent text-text-primary"
                : "border-transparent text-text-secondary hover:text-text-primary",
            )}
          >
            {it.label}
          </button>
        );
      })}
    </div>
  );
}
