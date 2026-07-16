import { TopBar } from "@/components/shell/TopBar";
import { AccountSettingsView } from "@/components/settings/AccountSettingsView";

export default function SettingsPage() {
  return (
    <>
      <TopBar title="User Profile & Settings" />
      <AccountSettingsView />
    </>
  );
}
