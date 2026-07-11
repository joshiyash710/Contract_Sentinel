import clsx from "clsx";
import type { InputHTMLAttributes } from "react";
import { Search } from "lucide-react";

export function SearchInput({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className={clsx("relative", className)}>
      <Search
        size={16}
        className="absolute inset-y-0 left-3 my-auto h-4 w-4 text-text-tertiary pointer-events-none"
      />
      <input
        type="search"
        placeholder="Search..."
        className="w-full bg-card-raised border border-subtle rounded-input pl-9 pr-3 py-2.5 text-body text-text-primary placeholder:text-text-tertiary outline-none focus:border-border-focus transition"
        {...rest}
      />
    </div>
  );
}
