import { TopBar } from "@/components/shell/TopBar";
import { IntegrationsView } from "@/components/integrations/IntegrationsView";

export default function IntegrationsPage() {
  return (
    <>
      <TopBar title="Integrations" />
      <IntegrationsView />
    </>
  );
}
