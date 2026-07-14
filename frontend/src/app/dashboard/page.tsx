import { TopBar } from "@/components/shell/TopBar";
import { SearchInput } from "@/components/ui/SearchInput";
import { DashboardView } from "@/components/dashboard/DashboardView";

// Server shell — the live, data-driven body is the client DashboardView (feature 018).
export default function DashboardPage() {
  return (
    <>
      <TopBar search={<SearchInput />} userName="Sarah Jenkins" />
      <DashboardView />
    </>
  );
}
