import { TopBar } from "@/components/shell/TopBar";
import { ReportHistoryView } from "@/components/history/ReportHistoryView";

// Server shell — the live, data-driven body is the client ReportHistoryView (feature 021).
// The "Contracts" nav now lands here (the history list); upload moved to a button (021 D1),
// reversing the 015 D5 redirect("/upload").
export default function ContractsPage() {
  return (
    <>
      <TopBar title="Contracts" />
      <ReportHistoryView />
    </>
  );
}
