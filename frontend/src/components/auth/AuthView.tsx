"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { getApiClient } from "@/lib/api/provider";
import { ApiError } from "@/lib/api/client";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { TextInput } from "@/components/ui/TextInput";
import { AuthBrandPanel } from "./AuthBrandPanel";

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

/** Feature 019 — split-layout auth (brand panel + form card), underline tabs. All 014
 *  behavior preserved (SSO disabled, forgot inert, error mapping, → /dashboard on success). */
export function AuthView({ defaultTab = "login" }: Props) {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>(defaultTab);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
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
        await client.signup(email, password, name, title.trim() || undefined);
      }
      router.replace("/dashboard");
    } catch (err) {
      setError(mapError(err, tab));
    } finally {
      setLoading(false);
    }
  }

  function switchTab(t: Tab) {
    setTab(t);
    setError(null);
  }

  return (
    <div className="grid min-h-screen bg-app md:grid-cols-2">
      <AuthBrandPanel />

      {/* Form column */}
      <div className="flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-md">
          {/* Logo (visible on mobile where the brand panel is hidden) */}
          <div className="mb-8 flex items-center justify-center gap-2.5 md:hidden">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-gradient text-accent-fg font-bold shadow-glow">
              C
            </span>
            <span className="text-h3 font-semibold tracking-tight text-text-primary">
              ContractSentinel
            </span>
          </div>

          <div className="rounded-2xl border border-subtle bg-card p-8 shadow-lg shadow-black/30">
            <h1 className="mb-1 text-h2 font-bold text-text-primary">
              {tab === "login" ? "Welcome back" : "Create your account"}
            </h1>
            <p className="mb-6 text-small text-text-secondary">
              {tab === "login"
                ? "Log in to your private workspace."
                : "Start analyzing contracts in minutes."}
            </p>

            {/* Underline tabs */}
            <div className="mb-6 flex gap-6 border-b border-subtle" role="tablist">
              {(["login", "signup"] as Tab[]).map((t) => (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={tab === t}
                  onClick={() => switchTab(t)}
                  className={`-mb-px border-b-2 pb-3 text-body font-medium transition ${
                    tab === t
                      ? "border-accent text-text-primary"
                      : "border-transparent text-text-tertiary hover:text-text-secondary"
                  }`}
                >
                  {t === "login" ? "Log In" : "Sign Up"}
                </button>
              ))}
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              {tab === "signup" && (
                <>
                  <div>
                    <label
                      htmlFor="name"
                      className="mb-1.5 block text-small font-medium text-text-secondary"
                    >
                      Full Name
                    </label>
                    <TextInput
                      id="name"
                      type="text"
                      autoComplete="name"
                      placeholder="Jane Doe"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      required
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="title"
                      className="mb-1.5 block text-small font-medium text-text-secondary"
                    >
                      Job Title <span className="text-text-tertiary">(optional)</span>
                    </label>
                    <TextInput
                      id="title"
                      type="text"
                      autoComplete="organization-title"
                      placeholder="Legal Counsel"
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                    />
                  </div>
                </>
              )}
              <div>
                <label
                  htmlFor="email"
                  className="mb-1.5 block text-small font-medium text-text-secondary"
                >
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
                  <label
                    htmlFor="password"
                    className="block text-small font-medium text-text-secondary"
                  >
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
                <p role="alert" className="rounded-input border border-risk-high/40 bg-risk-high/10 px-3 py-2 text-small text-risk-high">
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={loading}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent-gradient py-2.5 text-body font-semibold text-accent-fg shadow-glow transition hover:opacity-95 disabled:opacity-60"
              >
                {loading ? "Please wait…" : "Continue to ContractSentinel"}
                {!loading && <ArrowRight size={16} />}
              </button>
            </form>

            {/* Divider */}
            <div className="my-5 flex items-center gap-3">
              <div className="flex-1 border-t border-subtle" />
              <span className="text-small text-text-tertiary">Or continue with</span>
              <div className="flex-1 border-t border-subtle" />
            </div>

            {/* SSO — disabled (014 D6) */}
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                disabled
                title="Coming soon"
                className="flex cursor-not-allowed items-center justify-center gap-2 rounded-lg border border-subtle bg-card-raised py-2.5 text-small font-medium text-text-secondary opacity-50"
              >
                <GoogleGlyph />
                Google
              </button>
              <button
                type="button"
                disabled
                title="Coming soon"
                className="flex cursor-not-allowed items-center justify-center gap-2 rounded-lg border border-subtle bg-card-raised py-2.5 text-small font-medium text-text-secondary opacity-50"
              >
                <MicrosoftGlyph />
                Microsoft
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Monochrome brand glyphs (currentColor) — the SSO buttons are disabled placeholders, and
// hex color literals are confined to the design-token files (tokens.test.tsx / 013 AC-1).
function GoogleGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path opacity="0.9" d="M12 4.5c1.9 0 3.2.8 3.9 1.5l2.6-2.6C16.9 1.7 14.7.9 12 .9 7.7.9 4 3.4 2.2 7l3 2.3C6.1 6.5 8.8 4.5 12 4.5z" />
      <path opacity="0.65" d="M23.1 12.3c0-.8-.1-1.4-.2-2H12v3.9h6.3c-.1 1-.8 2.5-2.3 3.5l3 2.3c1.8-1.7 2.8-4.1 2.8-7.7z" />
      <path opacity="0.5" d="M5.2 14.3a7 7 0 0 1 0-4.5l-3-2.3a11.6 11.6 0 0 0 0 9.1z" />
      <path opacity="0.8" d="M12 23.1c3 0 5.5-1 7.3-2.7l-3-2.3c-.8.6-2 1-4.3 1-3.2 0-5.9-2-6.8-4.8l-3 2.3C4 20.6 7.7 23.1 12 23.1z" />
    </svg>
  );
}

function MicrosoftGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <rect x="2" y="2" width="9.2" height="9.2" />
      <rect x="12.8" y="2" width="9.2" height="9.2" opacity="0.75" />
      <rect x="2" y="12.8" width="9.2" height="9.2" opacity="0.75" />
      <rect x="12.8" y="12.8" width="9.2" height="9.2" opacity="0.5" />
    </svg>
  );
}
