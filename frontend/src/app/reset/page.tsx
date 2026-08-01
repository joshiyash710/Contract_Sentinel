"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { getApiClient } from "@/lib/api/provider";
import { ApiError } from "@/lib/api/client";
import { LogoMark } from "@/components/ui/LogoMark";
import { PasswordInput } from "@/components/ui/PasswordInput";

function ResetForm() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params?.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setLoading(true);
    try {
      await getApiClient().resetPassword(token, password);
      // Success: all old sessions are invalidated server-side; log in fresh.
      router.replace("/login?reset=1");
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setError("Password must be between 8 and 128 characters.");
      } else {
        setError("This reset link is invalid or has expired.");
      }
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <h1 className="mb-1 text-h2 font-bold text-text-primary">Choose a new password</h1>
        <p className="text-small text-text-secondary">Enter a new password for your account.</p>
      </div>
      <div>
        <label
          htmlFor="password"
          className="mb-1.5 block text-small font-medium text-text-secondary"
        >
          New password
        </label>
        <PasswordInput
          id="password"
          autoComplete="new-password"
          placeholder="••••••••"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      <div>
        <label
          htmlFor="confirm"
          className="mb-1.5 block text-small font-medium text-text-secondary"
        >
          Confirm password
        </label>
        <PasswordInput
          id="confirm"
          autoComplete="new-password"
          placeholder="••••••••"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
      </div>
      {error && (
        <p
          role="alert"
          className="rounded-input border border-risk-high/40 bg-risk-high/10 px-3 py-2 text-small text-risk-high"
        >
          {error}{" "}
          <Link href="/forgot-password" className="underline">
            Request a new link
          </Link>
          .
        </p>
      )}
      <button
        type="submit"
        disabled={loading}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent-gradient py-2.5 text-body font-semibold text-accent-fg shadow-glow transition hover:opacity-95 disabled:opacity-60"
      >
        {loading ? "Resetting…" : "Reset password"}
      </button>
    </form>
  );
}

/** Feature 034 — set a new password using the emailed token (?token=...). */
export default function ResetPasswordPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-app px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 flex items-center justify-center gap-2.5">
          <LogoMark size={32} />
          <span className="text-h3 font-semibold tracking-tight text-text-primary">
            ContractSentinel
          </span>
        </div>
        <div className="rounded-2xl border border-subtle bg-card p-8 shadow-lg shadow-black/30">
          <Suspense fallback={null}>
            <ResetForm />
          </Suspense>
        </div>
      </div>
    </div>
  );
}
