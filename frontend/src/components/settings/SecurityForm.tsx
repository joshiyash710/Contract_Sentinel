"use client";

import { useState } from "react";
import { getApiClient } from "@/lib/api/provider";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { Button } from "@/components/ui/Button";

type Status = { kind: "idle" | "saving" | "saved" | "error"; message?: string };

/** Security tab (spec 023) — change password: verify current, set new (confirm checked here). */
export function SecurityForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== confirm) {
      setStatus({ kind: "error", message: "New passwords don't match." });
      return;
    }
    setStatus({ kind: "saving" });
    try {
      await getApiClient().changePassword({ current_password: current, new_password: next });
      setStatus({ kind: "saved", message: "Password updated." });
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      const message =
        err instanceof Error && err.message ? err.message : "Couldn't change your password.";
      setStatus({ kind: "error", message });
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <Field label="Current Password" htmlFor="settings-current">
        <PasswordInput
          id="settings-current"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          autoComplete="current-password"
        />
      </Field>
      <Field label="New Password" htmlFor="settings-new" hint="At least 8 characters.">
        <PasswordInput
          id="settings-new"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          autoComplete="new-password"
        />
      </Field>
      <Field label="Confirm New Password" htmlFor="settings-confirm">
        <PasswordInput
          id="settings-confirm"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          autoComplete="new-password"
        />
      </Field>

      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" disabled={status.kind === "saving"}>
          {status.kind === "saving" ? "Updating…" : "Update password"}
        </Button>
        {status.message && (
          <span
            role="status"
            className={status.kind === "error" ? "text-small text-risk-high" : "text-small text-risk-low"}
          >
            {status.message}
          </span>
        )}
      </div>
    </form>
  );
}

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1.5 block text-small font-medium text-text-secondary">
        {label}
      </label>
      {children}
      {hint && <p className="mt-1 text-caption text-text-tertiary">{hint}</p>}
    </div>
  );
}
