"use client";

import clsx from "clsx";
import { useState, type InputHTMLAttributes } from "react";
import { Eye, EyeOff } from "lucide-react";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type">;

export function PasswordInput({ className, ...rest }: Props) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <input
        type={visible ? "text" : "password"}
        className={clsx(
          "w-full bg-card-raised border border-subtle rounded-input px-3 py-2.5 pr-10 text-body text-text-primary placeholder:text-text-tertiary outline-none focus:border-border-focus transition",
          className,
        )}
        {...rest}
      />
      <button
        type="button"
        aria-label={visible ? "Hide password" : "Show password"}
        onClick={() => setVisible((v) => !v)}
        className="absolute inset-y-0 right-2 my-auto h-8 w-8 flex items-center justify-center text-text-tertiary hover:text-text-secondary"
      >
        {visible ? <EyeOff size={18} /> : <Eye size={18} />}
      </button>
    </div>
  );
}
