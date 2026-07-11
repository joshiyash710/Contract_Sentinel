"use client";

import { useRouter } from "next/navigation";
import { CheckCircle2, AlertTriangle, WifiOff } from "lucide-react";
import { useJobEvents } from "@/lib/useJobEvents";
import { getApiClient } from "@/lib/api/provider";
import { nodeLabel } from "@/lib/jobLabels";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Button } from "@/components/ui/Button";
import { ProcessingArt } from "./ProcessingArt";

/**
 * Live processing screen (spec 015 §2.4 / plan §3.6). Driven by useJobEvents(jobId) → renders by
 * phase. Reaches the backend only via getApiClient() (spec AC-16).
 */
export function ProcessingView({ jobId }: { jobId: string }) {
  const router = useRouter();
  const { state, reconnect } = useJobEvents(jobId);
  const client = getApiClient();

  // ── terminal: failed ──────────────────────────────────────────────────────
  if (state.phase === "failed") {
    return (
      <Centered>
        <AlertTriangle size={48} className="text-risk-high" />
        <h2 className="text-h2 font-bold">Analysis failed</h2>
        <p className="text-body text-text-secondary">
          {state.final?.error?.message ?? "Something went wrong while analyzing your contract."}
        </p>
        <Button variant="primary" onClick={() => router.push("/upload")}>
          Retry
        </Button>
      </Centered>
    );
  }

  // ── recoverable: connection lost / job not found ──────────────────────────
  if (state.phase === "error") {
    return (
      <Centered>
        <WifiOff size={48} className="text-text-tertiary" />
        <h2 className="text-h2 font-bold">Connection lost</h2>
        <p className="text-body text-text-secondary">
          {state.errorMessage ?? "We lost the connection to the analysis stream."}
        </p>
        <Button variant="secondary" onClick={reconnect}>
          Refresh
        </Button>
      </Centered>
    );
  }

  // ── terminal: completed (possibly completed-with-issue, EC-1) ─────────────
  if (state.phase === "completed") {
    const issue = state.final?.error; // completed-with-issue branch (review B1)
    const reportAvailable = state.final?.report_available;
    return (
      <Centered>
        {issue ? (
          <AlertTriangle size={48} className="text-risk-medium" />
        ) : (
          <CheckCircle2 size={48} className="text-risk-low" />
        )}
        <h2 className="text-h2 font-bold">
          {issue ? "Analysis finished with an issue" : "Analysis complete"}
        </h2>
        {issue && <p className="text-body text-text-secondary">{issue.message}</p>}
        {reportAvailable && (
          <div className="flex items-center gap-3">
            <a
              href={client.getReportUrl(jobId, "md")}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-input bg-accent-gradient px-4 py-2.5 font-semibold text-accent-fg hover:opacity-95"
            >
              View report
            </a>
            <a
              href={client.getReportUrl(jobId, "json")}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-input border border-subtle px-4 py-2.5 font-medium text-text-primary hover:bg-card-raised"
            >
              View JSON
            </a>
          </div>
        )}
      </Centered>
    );
  }

  // ── running / connecting ──────────────────────────────────────────────────
  const hasStep = state.index != null && state.total != null && state.total > 0;
  const pct = hasStep ? Math.round((state.index! / state.total!) * 100) : 0;
  return (
    <Centered>
      <ProcessingArt />
      <div className="w-full max-w-md text-center">
        <h2 className="text-h3 font-semibold text-text-primary">
          {state.phase === "connecting" ? "Starting analysis…" : nodeLabel(state.node)}
        </h2>
        {hasStep ? (
          <>
            <p className="mt-1 text-small text-text-secondary">
              Step {state.index} of {state.total}
            </p>
            <ProgressBar value={pct} className="mt-4" />
          </>
        ) : (
          <p className="mt-1 text-small text-text-secondary">Queued — waiting for the pipeline…</p>
        )}
        {/* prior completed steps only — the latest node is shown in the header above */}
        {state.completedNodes.length > 1 && (
          <ul className="mt-6 space-y-1 text-left text-small text-text-tertiary">
            {state.completedNodes.slice(0, -1).map((n, i) => (
              <li key={i} className="flex items-center gap-2">
                <CheckCircle2 size={14} className="text-risk-low" /> {nodeLabel(n)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Centered>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-[calc(100vh-0px)] flex-col items-center justify-center gap-4 p-6 text-center">
      {children}
    </div>
  );
}
