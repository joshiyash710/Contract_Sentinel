import { ReportView } from "@/components/report/ReportView";

export default function ReportPage({ params }: { params: { jobId: string } }) {
  return (
    <div className="min-h-screen bg-app">
      <ReportView jobId={params.jobId} />
    </div>
  );
}
