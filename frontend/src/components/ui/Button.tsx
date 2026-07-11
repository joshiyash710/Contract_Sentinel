import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "chip";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  children: ReactNode;
}

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-accent-gradient text-accent-fg rounded-input px-4 py-2.5 font-semibold hover:opacity-95",
  secondary:
    "border border-subtle text-text-primary rounded-input px-4 py-2.5 font-medium hover:bg-card-raised",
  ghost: "text-text-secondary rounded-input p-2 hover:bg-card-raised hover:text-text-primary",
  // chip = small pill action (screens 5/6/7 suggestion chips)
  chip: "bg-card-raised text-text-primary rounded-pill px-3 py-1.5 text-small border border-subtle hover:border-accent",
};

export function Button({ variant = "primary", className, children, ...rest }: ButtonProps) {
  return (
    <button
      className={clsx(
        VARIANTS[variant],
        "inline-flex items-center justify-center gap-2 transition disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
