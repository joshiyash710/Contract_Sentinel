"use client";

import { useEffect, useMemo, useState } from "react";
import { HardDrive, Mail, CheckCircle2, type LucideIcon } from "lucide-react";
import { useCurrentUser } from "@/lib/useCurrentUser";
import { getApiClient } from "@/lib/api/provider";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";

/**
 * Integrations page. Google Drive is now PER-USER (feature 031): each account connects its own
 * Google so its reports save to that user's own Drive. Gmail stays server-managed — reports are
 * emailed FROM the app account TO the user (feature 020/030). Notion/Slack/Dropbox/Team are §2-cut.
 */
export function IntegrationsView() {
  const { email } = useCurrentUser();
  const destination = email?.trim() || "your account email";
  const api = useMemo(() => getApiClient(), []);

  const [drive, setDrive] = useState<{ connected: boolean; googleEmail?: string | null } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);

  useEffect(() => {
    api.getGoogleDriveStatus().then(setDrive).catch(() => setDrive({ connected: false }));
    const params = new URLSearchParams(window.location.search);
    const g = params.get("google");
    if (g === "connected") setBanner("Google Drive connected.");
    else if (g === "denied") setBanner("Google Drive connection was cancelled.");
    else if (g === "error") setBanner("Could not connect Google Drive — please try again.");
  }, [api]);

  function connect() {
    window.location.href = api.googleDriveAuthorizeUrl();
  }

  async function disconnect() {
    setBusy(true);
    try {
      await api.disconnectGoogleDrive();
      setDrive({ connected: false });
      setBanner("Google Drive disconnected.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 p-6">
      <p className="max-w-2xl text-body text-text-secondary">
        ContractSentinel delivers every finished analysis report through these connected services.
      </p>

      {banner && (
        <Card className="max-w-2xl border-accent/40 p-3 text-small text-text-secondary">{banner}</Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {/* Google Drive — per-user (feature 031) */}
        <Card className="flex flex-col gap-3 p-5">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-input bg-card-raised text-accent">
              <HardDrive size={20} />
            </span>
            <h3 className="text-h3 font-semibold text-text-primary">Google Drive</h3>
          </div>
          <p className="text-body text-text-secondary">
            Your analysis reports are automatically saved to your own Google Drive.
          </p>
          <div className="mt-auto pt-1">
            {drive === null ? (
              <Button variant="secondary" disabled className="text-small">
                Checking…
              </Button>
            ) : drive.connected ? (
              <div className="flex flex-col gap-2">
                <span className="flex items-center gap-1.5 text-small text-text-secondary">
                  <CheckCircle2 size={15} className="text-risk-low" />
                  Connected{drive.googleEmail ? ` as ${drive.googleEmail}` : ""}
                </span>
                <Button
                  variant="secondary"
                  onClick={disconnect}
                  disabled={busy}
                  className="text-small"
                >
                  Disconnect
                </Button>
              </div>
            ) : (
              <Button variant="primary" onClick={connect} className="text-small">
                Connect Google Drive
              </Button>
            )}
          </div>
        </Card>

        {/* Gmail — server-managed (central), unchanged */}
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
          When an analysis finishes, its report is emailed to you and — if you&apos;ve connected
          Google Drive — saved to your own Drive. Email delivery is managed by ContractSentinel.
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
          Server-managed
        </Button>
      </div>
    </Card>
  );
}
