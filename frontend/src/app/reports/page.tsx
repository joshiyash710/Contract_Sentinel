import { TopBar } from "@/components/shell/TopBar";
import { ReportsView } from "@/components/dashboard/ReportsView";

// Server shell — the live, data-driven body is the client ReportsView (feature 018).
export default function ReportsPage() {
  return (
    <>
      <TopBar title="Risk Dashboard" userName="Sarah Jenkins" />
      <ReportsView />
    </>
  );
}
