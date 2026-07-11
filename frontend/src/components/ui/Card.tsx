import clsx from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  glow?: boolean;
  children: ReactNode;
}

export function Card({ glow = false, className, children, ...rest }: CardProps) {
  return (
    <div
      className={clsx(
        "bg-card border border-subtle rounded-card p-5 shadow-lg shadow-black/20",
        glow && "shadow-glow",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}
