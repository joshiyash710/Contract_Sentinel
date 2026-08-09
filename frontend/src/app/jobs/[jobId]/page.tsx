import { ProcessingView } from "@/components/processing/ProcessingView";

// Next 16: dynamic-route `params` is a Promise (async request API). Await it.
export default async function JobPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;
  return (
    <div className="min-h-screen">
      <ProcessingView jobId={jobId} />
    </div>
  );
}
