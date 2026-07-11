"use client";

import clsx from "clsx";
import { useState } from "react";
import { ChevronDown } from "lucide-react";

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
}

// Generic select/menu (filter dropdowns on screens 3/12; top-bar account menu). spec AC-12a.
export function Dropdown({ options, value, onSelect, placeholder = "Select", className }: DropdownProps) {
  const [open, setOpen] = useState(false);
  const selected = options.find((o) => o.value === value);

  return (
    <div className={clsx("relative inline-block", className)}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-2 rounded-input border border-subtle bg-card-raised px-3 py-2 text-body text-text-primary hover:border-accent"
      >
        <span className={clsx(!selected && "text-text-tertiary")}>
          {selected ? selected.label : placeholder}
        </span>
        <ChevronDown size={16} className="text-text-tertiary" />
      </button>
      {open && (
        <ul
          role="listbox"
          className="absolute z-10 mt-1 min-w-full rounded-input border border-subtle bg-card py-1 shadow-glow"
        >
          {options.map((o) => (
            <li key={o.value}>
              <button
                type="button"
                role="option"
                aria-selected={o.value === value}
                onClick={() => {
                  onSelect(o.value);
                  setOpen(false);
                }}
                className={clsx(
                  "block w-full px-3 py-1.5 text-left text-body hover:bg-card-raised",
                  o.value === value ? "text-accent" : "text-text-primary",
                )}
              >
                {o.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
