import { TopBar } from "@/components/shell/TopBar";
import { Card } from "@/components/ui/Card";

export default function ContractsPage() {
  return (
    <>
      <TopBar title="Contracts" userName="Sarah Jenkins" />
      <div className="p-6">
        <Card className="max-w-2xl">
          <h2 className="text-h3 font-semibold">Contracts</h2>
          <p className="mt-1 text-body text-text-secondary">
            The upload, analysis-workspace, and history screens are built on this foundation in
            specs 015–017.
          </p>
        </Card>
      </div>
    </>
  );
}
