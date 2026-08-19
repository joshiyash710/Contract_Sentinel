"use client";

import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";

export interface DropdownOption {
  value: string;
  label: string;
}

interface DropdownProps {
  options: DropdownOption[];
  value?: string;
  onSelect: (value: string) => void;
  placeholder?: string;
  className?: string;
  /** Accessible name for the trigger when there is no visible <label>. */
  ariaLabel?: string;
}

// Generic select/menu (filter dropdowns on screens 3/12; top-bar account menu). spec AC-12a.
// Custom-rendered (not a native <select>) so the open panel inherits the app's frosted-glass theme
// instead of the browser's opaque white/blue OS popup.
export function Dropdown({
  options,
  value,
  onSelect,
  placeholder = "Select",
  className,
  ariaLabel,
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const selected = options.find((o) => o.value === value);

  // Close on outside-click or Escape (native <select> got this for free).
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={rootRef} className={clsx("relative inline-block", className)}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => setOpen((o) => !o)}
        className="press inline-flex w-full items-center justify-between gap-2 rounded-input border border-white/10 bg-white/[0.06] px-3 py-2.5 text-body text-text-primary backdrop-blur-md outline-none transition hover:border-white/20 focus-visible:border-border-focus"
      >
        <span className={clsx(!selected && "text-text-tertiary")}>
          {selected ? selected.label : placeholder}
        </span>
        <ChevronDown
          size={16}
          className={clsx("text-text-tertiary transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <ul
          role="listbox"
          // Solid raised surface (not the translucent .glass fill) so the menu is fully opaque and
          // the table behind it does not bleed through. Themed border + shadow keep the glass feel.
          className="reveal absolute z-30 mt-2 min-w-full overflow-hidden rounded-input border border-white/10 bg-card-raised p-1 shadow-[var(--glass-shadow)]"
        >
          {options.map((o) => {
            const isSelected = o.value === value;
            return (
              <li key={o.value}>
                <button
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => {
                    onSelect(o.value);
                    setOpen(false);
                  }}
                  className={clsx(
                    "flex w-full items-center justify-between gap-3 rounded-[calc(var(--radius-input)-4px)] px-3 py-2 text-left text-body transition",
                    isSelected
                      ? "bg-accent/15 text-accent"
                      : "text-text-secondary hover:bg-white/[0.06] hover:text-text-primary",
                  )}
                >
                  <span className="whitespace-nowrap">{o.label}</span>
                  {isSelected && <Check size={15} className="shrink-0" />}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
