import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "chip";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  children: ReactNode;
}

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "sheen bg-accent-gradient text-accent-fg rounded-input px-4 py-2.5 font-semibold shadow-glow hover:opacity-95 [box-shadow:var(--glow-accent),inset_0_1px_0_0_rgba(255,255,255,0.25)]",
  secondary:
    "glass text-text-primary rounded-input px-4 py-2.5 font-medium hover:border-accent/40",
  ghost: "text-text-secondary rounded-input p-2 hover:bg-card-raised hover:text-text-primary",
  // chip = small pill action (screens 5/6/7 suggestion chips)
  chip: "glass text-text-primary rounded-pill px-3 py-1.5 text-small hover:border-accent/50",
};

export function Button({ variant = "primary", className, children, ...rest }: ButtonProps) {
  return (
    <button
      className={clsx(
        VARIANTS[variant],
        "press inline-flex items-center justify-center gap-2 transition disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
