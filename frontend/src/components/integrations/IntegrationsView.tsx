"use client";

import { HardDrive, Mail, CheckCircle2, type LucideIcon } from "lucide-react";
import { useCurrentUser } from "@/lib/useCurrentUser";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";

/**
 * Integrations page (spec 024) — the two integrations the product actually uses, Google Drive +
 * Gmail, which power automatic report delivery (010: on completion a report is saved to Drive and
 * emailed to the owner, 020). Notion/Slack/Dropbox/Team are §2-cut. The connection is
 * server-managed (no per-user OAuth), so the affordance is disabled/informational (D3/D5).
 */
export function IntegrationsView() {
  const { email } = useCurrentUser();
  const destination = email?.trim() || "your account email";

  return (
    <div className="space-y-6 p-6">
      <p className="max-w-2xl text-body text-text-secondary">
        ContractSentinel delivers every finished analysis report through these connected services.
      </p>

      <div className="grid gap-4 sm:grid-cols-2">
        <IntegrationCard
          name="Google Drive"
          Icon={HardDrive}
          tone="text-accent"
          description="Your analysis reports are automatically saved to Google Drive."
        />
        <IntegrationCard
          name="Gmail"
          Icon={Mail}
          tone="text-risk-medium"
          description={`Finished reports are emailed to you at ${destination}.`}
        />
      </div>

      <Card className="max-w-2xl p-5">
        <h3 className="text-body font-semibold text-text-primary">How delivery works</h3>
        <p className="mt-1 text-small text-text-secondary">
          When an analysis finishes, its report is saved to your Google Drive and emailed to you.
          These integrations are managed by ContractSentinel — there&apos;s nothing to set up.
        </p>
      </Card>
    </div>
  );
}

function IntegrationCard({
  name,
  Icon,
  tone,
  description,
}: {
  name: string;
  Icon: LucideIcon;
  tone: string;
  description: string;
}) {
  return (
    <Card className="flex flex-col gap-3 p-5">
      <div className="flex items-center gap-3">
        <span className={`flex h-10 w-10 items-center justify-center rounded-input bg-card-raised ${tone}`}>
          <Icon size={20} />
        </span>
        <h3 className="text-h3 font-semibold text-text-primary">{name}</h3>
      </div>
      <p className="text-body text-text-secondary">{description}</p>
      <div className="mt-auto pt-1">
        <Button variant="secondary" disabled className="text-small">
          <CheckCircle2 size={15} className="text-risk-low" />
          Connected · Managed by ContractSentinel
        </Button>
      </div>
    </Card>
  );
}
