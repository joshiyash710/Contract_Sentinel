import { ProcessingView } from "@/components/processing/ProcessingView";

export default function JobPage({ params }: { params: { jobId: string } }) {
  return (
    <div className="min-h-screen bg-app">
      <ProcessingView jobId={params.jobId} />
    </div>
  );
}
