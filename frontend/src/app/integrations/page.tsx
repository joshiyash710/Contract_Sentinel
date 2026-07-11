import { TopBar } from "@/components/shell/TopBar";
import { Card } from "@/components/ui/Card";

export default function IntegrationsPage() {
  return (
    <>
      <TopBar title="Integrations" userName="Sarah Jenkins" />
      <div className="p-6">
        <Card className="max-w-2xl">
          <h2 className="text-h3 font-semibold">Integrations</h2>
          <p className="mt-1 text-body text-text-secondary">
            Google Drive + Gmail only (constitution §2). The integrations screen is built in
            spec 018.
          </p>
        </Card>
      </div>
    </>
  );
}
