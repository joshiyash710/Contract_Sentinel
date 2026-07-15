"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, FileQuestion, Download } from "lucide-react";
import { useReport } from "@/lib/useReport";
import { getApiClient } from "@/lib/api/provider";
import type { ContractReport } from "@/lib/api/types";
import { Button } from "@/components/ui/Button";
import { AnalysisWorkspace } from "./AnalysisWorkspace";

/** The report destination screen (spec 017). Reaches the backend only via getApiClient(). */
export function ReportView({ jobId }: { jobId: string }) {
  const router = useRouter();
  const { state, retry } = useReport(jobId);

  // 409 / non-terminal job → go watch it finish; D1 auto-redirects back here on completion.
  useEffect(() => {
    if (state.phase === "redirecting") router.replace(`/jobs/${jobId}`);
  }, [state.phase, jobId, router]);

  if (state.phase === "loading") {
    return <Centered>{<p className="text-body text-text-secondary">Loading your report…</p>}</Centered>;
  }

  if (state.phase === "redirecting") {
    return (
      <Centered>
        <p className="text-body text-text-secondary">Finishing analysis…</p>
      </Centered>
    );
  }

  if (state.phase === "not_found") {
    return (
      <Centered>
        <FileQuestion size={48} className="text-text-tertiary" />
        <h2 className="text-h2 font-bold">We couldn&apos;t find that report</h2>
        <p className="text-body text-text-secondary">
          This job may have expired or the link is incorrect.
        </p>
        <a href="/upload" className="text-accent font-medium hover:underline">
          Upload a new contract
        </a>
      </Centered>
    );
  }

  if (state.phase === "artifact_unavailable") {
    return (
      <Centered>
        <AlertTriangle size={48} className="text-risk-medium" />
        <h2 className="text-h2 font-bold">This report is no longer available</h2>
        <p className="text-body text-text-secondary">
          The analysis finished, but its report files are no longer on the server.
        </p>
        <a href="/upload" className="text-accent font-medium hover:underline">
          Start a new analysis
        </a>
      </Centered>
    );
  }

  if (state.phase === "error") {
    return (
      <Centered>
        <AlertTriangle size={48} className="text-risk-high" />
        <h2 className="text-h2 font-bold">We couldn&apos;t load the report</h2>
        <p className="text-body text-text-secondary">{state.message}</p>
        <Button variant="primary" onClick={retry}>
          Try again
        </Button>
      </Centered>
    );
  }

  // loaded
  const report = state.report as ContractReport;

  if (report.ingest_error) {
    return <IngestErrorPanel jobId={jobId} report={report} />;
  }

  return <AnalysisWorkspace jobId={jobId} report={report} />;
}

/** Minimal "could not process" report (009 Edge Case 1 / spec 017 D6). */
function IngestErrorPanel({ jobId, report }: { jobId: string; report: ContractReport }) {
  const client = getApiClient();
  const message = String(
    (report.ingest_error as { message?: unknown } | null)?.message ??
      JSON.stringify(report.ingest_error),
  );
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <div className="rounded-card border border-subtle bg-card p-8 text-center">
        <AlertTriangle size={44} className="mx-auto text-risk-high" />
        <h1 className="mt-3 text-h2 font-bold">We couldn&apos;t fully process this contract</h1>
        <p className="mt-1 text-body text-text-secondary">{report.original_filename}</p>
        <p className="mt-3 text-body text-text-secondary">{message}</p>
        <div className="mt-5 flex items-center justify-center gap-2">
          <a
            href={client.getReportUrl(jobId, "md")}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-input border border-subtle px-4 py-2.5 font-medium text-text-primary hover:bg-card-raised"
          >
            <Download size={16} /> Download report (Markdown)
          </a>
          <a href="/upload" className="text-accent font-medium hover:underline">
            Try another file
          </a>
        </div>
      </div>
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-6 text-center">
      {children}
    </div>
  );
}
