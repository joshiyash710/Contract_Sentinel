import clsx from "clsx";
import type { InputHTMLAttributes } from "react";

const FIELD =
  "w-full bg-card-raised border border-subtle rounded-input px-3 py-2.5 text-body text-text-primary placeholder:text-text-tertiary outline-none focus:border-border-focus transition";

export function TextInput({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={clsx(FIELD, className)} {...rest} />;
}
