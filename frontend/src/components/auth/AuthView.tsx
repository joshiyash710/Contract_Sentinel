"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Shield } from "lucide-react";
import { getApiClient } from "@/lib/api/provider";
import { ApiError } from "@/lib/api/client";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { TextInput } from "@/components/ui/TextInput";

type Tab = "login" | "signup";

interface Props {
  defaultTab?: Tab;
}

function mapError(err: unknown, tab: Tab): string {
  if (err instanceof ApiError) {
    if (tab === "login") return "Invalid email or password.";
    if (err.status === 409) return "An account with this email already exists.";
    if (err.status === 422) return "Password must be between 8 and 128 characters.";
    return "Something went wrong. Please try again.";
  }
  return "Something went wrong. Please try again.";
}

export function AuthView({ defaultTab = "login" }: Props) {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>(defaultTab);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const client = getApiClient();
      if (tab === "login") {
        await client.login(email, password);
      } else {
        await client.signup(email, password);
      }
      router.replace("/dashboard");
    } catch (err) {
      setError(mapError(err, tab));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-app px-4">
      <div className="w-full max-w-md rounded-2xl bg-card border border-subtle p-8 shadow-card">
        {/* Logo */}
        <div className="mb-6 flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-gradient text-accent-fg font-bold shadow-glow">
            C
          </span>
          <span className="text-h3 font-semibold tracking-tight text-text-primary">
            ContractSentinel
          </span>
        </div>

        {/* Tabs */}
        <div className="mb-6 flex rounded-lg border border-subtle bg-card-raised p-1">
          {(["login", "signup"] as Tab[]).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => { setTab(t); setError(null); }}
              className={`flex-1 rounded-md py-1.5 text-body font-medium transition ${
                tab === t
                  ? "bg-accent text-accent-fg shadow-sm"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              {t === "login" ? "Log In" : "Sign Up"}
            </button>
          ))}
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="email" className="mb-1.5 block text-small font-medium text-text-secondary">
              Work Email
            </label>
            <TextInput
              id="email"
              type="email"
              autoComplete="email"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <label htmlFor="password" className="block text-small font-medium text-text-secondary">
                Password
              </label>
              {tab === "login" && (
                <span
                  className="cursor-not-allowed text-small text-text-tertiary"
                  aria-disabled="true"
                >
                  Forgot password?
                </span>
              )}
            </div>
            <PasswordInput
              id="password"
              autoComplete={tab === "login" ? "current-password" : "new-password"}
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          {error && (
            <p role="alert" className="text-small text-red-400">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-accent py-2.5 text-body font-semibold text-accent-fg shadow-glow transition hover:opacity-90 disabled:opacity-60"
          >
            {loading ? "Please wait…" : "Continue to ContractSentinel"}
          </button>
        </form>

        {/* Divider */}
        <div className="my-5 flex items-center gap-3">
          <div className="flex-1 border-t border-subtle" />
          <span className="text-small text-text-tertiary">or continue with</span>
          <div className="flex-1 border-t border-subtle" />
        </div>

        {/* SSO buttons — disabled (D6) */}
        <div className="grid grid-cols-2 gap-3">
          <button
            type="button"
            disabled
            title="Coming soon"
            className="flex items-center justify-center gap-2 rounded-lg border border-subtle bg-card-raised py-2.5 text-small font-medium text-text-secondary opacity-50 cursor-not-allowed"
          >
            <Shield size={16} />
            Google
          </button>
          <button
            type="button"
            disabled
            title="Coming soon"
            className="flex items-center justify-center gap-2 rounded-lg border border-subtle bg-card-raised py-2.5 text-small font-medium text-text-secondary opacity-50 cursor-not-allowed"
          >
            <Shield size={16} />
            Microsoft
          </button>
        </div>
      </div>
    </div>
  );
}
