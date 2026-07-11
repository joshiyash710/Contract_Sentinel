import { TopBar } from "@/components/shell/TopBar";
import { Card } from "@/components/ui/Card";

export default function SettingsPage() {
  return (
    <>
      <TopBar title="Settings" userName="Sarah Jenkins" />
      <div className="p-6">
        <Card className="max-w-2xl">
          <h2 className="text-h3 font-semibold">Settings</h2>
          <p className="mt-1 text-body text-text-secondary">
            The profile &amp; settings screen is built on this foundation in spec 018.
          </p>
        </Card>
      </div>
    </>
  );
}
