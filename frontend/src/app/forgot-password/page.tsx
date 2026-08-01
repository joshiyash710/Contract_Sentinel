"use client";

import { useState } from "react";
import Link from "next/link";
import { getApiClient } from "@/lib/api/provider";
import { LogoMark } from "@/components/ui/LogoMark";
import { TextInput } from "@/components/ui/TextInput";

/** Feature 034 — request a password-reset link. The server returns a generic response regardless of
 *  whether the email exists, so this page NEVER discloses account existence: on any (non-transport)
 *  outcome it shows the same confirmation. */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      await getApiClient().requestPasswordReset(email);
    } catch {
      /* Do not reveal transport errors as existence signals — show the same confirmation. */
    } finally {
      setLoading(false);
      setSent(true);
    }
  }

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
          {sent ? (
            <div>
              <h1 className="mb-1 text-h2 font-bold text-text-primary">Check your email</h1>
              <p className="text-small text-text-secondary">
                If an account exists for that email, we&apos;ve sent a link to reset your password.
                The link expires in 30 minutes.
              </p>
              <Link
                href="/login"
                className="mt-6 inline-block text-small text-text-tertiary hover:text-text-primary hover:underline"
              >
                Back to sign in
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <h1 className="mb-1 text-h2 font-bold text-text-primary">Reset your password</h1>
                <p className="text-small text-text-secondary">
                  Enter your account email and we&apos;ll send you a reset link.
                </p>
              </div>
              <div>
                <label
                  htmlFor="email"
                  className="mb-1.5 block text-small font-medium text-text-secondary"
                >
                  Email
                </label>
                <TextInput
                  id="email"
                  type="email"
                  autoComplete="email"
                  placeholder="you@company.com"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent-gradient py-2.5 text-body font-semibold text-accent-fg shadow-glow transition hover:opacity-95 disabled:opacity-60"
              >
                {loading ? "Sending…" : "Send reset link"}
              </button>
              <Link
                href="/login"
                className="block text-center text-small text-text-tertiary hover:text-text-primary hover:underline"
              >
                Back to sign in
              </Link>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
