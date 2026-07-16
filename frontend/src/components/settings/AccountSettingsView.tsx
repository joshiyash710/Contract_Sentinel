"use client";

import { useState } from "react";
import { useCurrentUser } from "@/lib/useCurrentUser";
import { Card } from "@/components/ui/Card";
import { Avatar } from "@/components/ui/Avatar";
import { Tabs } from "@/components/ui/Tabs";
import { ProfileForm } from "./ProfileForm";
import { SecurityForm } from "./SecurityForm";

const TABS = [
  { value: "profile", label: "Profile" },
  { value: "security", label: "Security" },
];

/**
 * Account settings (spec 023, design ref (3) "User Profile & Settings"): a left avatar column
 * card + a right tabbed content card (Profile / Security). Billing/Team are §2-cut and
 * Integrations is its own page (feature 024) — see D1/D8.
 */
export function AccountSettingsView() {
  const { displayName, title } = useCurrentUser();
  const [tab, setTab] = useState("profile");

  return (
    <div className="p-6">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,20rem)_1fr]">
        {/* Avatar column */}
        <Card className="flex flex-col items-center p-8 text-center">
          <Avatar name={displayName} size="lg" />
          <h2 className="mt-4 text-h3 font-semibold text-text-primary">{displayName}</h2>
          {title && <p className="mt-1 text-body text-text-secondary">{title}</p>}
        </Card>

        {/* Tabbed content */}
        <Card className="p-6">
          <Tabs items={TABS} value={tab} onChange={setTab} variant="underline" className="mb-6" />
          {tab === "profile" ? <ProfileForm /> : <SecurityForm />}
        </Card>
      </div>
    </div>
  );
}
