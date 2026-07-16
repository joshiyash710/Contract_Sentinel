"use client";

import { useEffect, useState } from "react";
import { getApiClient } from "@/lib/api/provider";
import { useCurrentUser, refreshCurrentUser } from "@/lib/useCurrentUser";
import { TextInput } from "@/components/ui/TextInput";
import { Button } from "@/components/ui/Button";

type Status = { kind: "idle" | "saving" | "saved" | "error"; message?: string };

/** Profile tab (spec 023) — edit name/title; email is read-only (D2). */
export function ProfileForm() {
  const { user, email } = useCurrentUser();
  const [name, setName] = useState(user?.name ?? "");
  const [title, setTitle] = useState(user?.title ?? "");
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  // Seed fields when the (async) current user arrives / changes.
  useEffect(() => {
    setName(user?.name ?? "");
    setTitle(user?.title ?? "");
  }, [user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setStatus({ kind: "error", message: "Please enter your name." });
      return;
    }
    setStatus({ kind: "saving" });
    try {
      await getApiClient().updateProfile({ name: name.trim(), title: title.trim() || null });
      await refreshCurrentUser();
      setStatus({ kind: "saved", message: "Profile updated." });
    } catch {
      setStatus({ kind: "error", message: "Couldn't update your profile. Please try again." });
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <Field label="Full Name" htmlFor="settings-name">
        <TextInput
          id="settings-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Your full name"
        />
      </Field>
      <Field label="Job Title" htmlFor="settings-title">
        <TextInput
          id="settings-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Legal Counsel"
        />
      </Field>
      <Field label="Email" htmlFor="settings-email" hint="Your email is used to sign in and can't be changed here.">
        <TextInput id="settings-email" value={email ?? ""} disabled readOnly />
      </Field>

      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" disabled={status.kind === "saving"}>
          {status.kind === "saving" ? "Saving…" : "Save"}
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
