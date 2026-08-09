"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, AlertTriangle, WifiOff, Lock, Loader2 } from "lucide-react";
import { useJobStatus } from "@/lib/useJobStatus";
import { useNavigationLock } from "@/lib/useNavigationLock";
import { nodeLabel } from "@/lib/jobLabels";
import { REPORT_REDIRECT_DELAY_MS } from "@/lib/reportConstants";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Button } from "@/components/ui/Button";
import { ProcessingArt } from "./ProcessingArt";

/**
 * Live processing screen (spec 015 §2.4 / plan §3.6). Driven by useJobEvents(jobId) → renders by
 * phase. Reaches the backend only via getApiClient() (spec AC-16).
 */
export function ProcessingView({ jobId }: { jobId: string }) {
  const router = useRouter();
  const { state, reconnect } = useJobStatus(jobId);

  // ── lock the user on this page while the pipeline is in flight ──────────────
  // Traps browser Back/Forward + warns on refresh/close so a running analysis can't be
  // abandoned; released the moment it finishes/fails so the auto-redirect can proceed.
  const pipelineRunning = state.phase === "connecting" || state.phase === "running";
  useNavigationLock(pipelineRunning);

  // ── auto-redirect to the report on a clean completion (spec 017 D1/D10) ────
  // Placed ABOVE the phase early-returns (Rules of Hooks). Gates on report_available
  // (INV-1 → no 409 bounce) and no job-level error (INV-3 → completed-with-issue stays inline).
  useEffect(() => {
    if (state.phase !== "completed") return;
    if (state.final?.error) return;
    if (!state.final?.report_available) return;
    const t = setTimeout(() => router.replace(`/jobs/${jobId}/report`), REPORT_REDIRECT_DELAY_MS);
    return () => clearTimeout(t);
  }, [state.phase, state.final?.error, state.final?.report_available, jobId, router]);

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

  // ── terminal: completed ───────────────────────────────────────────────────
  if (state.phase === "completed") {
    const issue = state.final?.error; // completed-with-issue (EC-1 / INV-3) stays inline
    if (issue) {
      return (
        <Centered>
          <AlertTriangle size={48} className="text-risk-medium" />
          <h2 className="text-h2 font-bold">Analysis finished with an issue</h2>
          <p className="text-body text-text-secondary">{issue.message}</p>
          {state.final?.report_available && (
            <Button variant="secondary" onClick={() => router.push(`/jobs/${jobId}/report`)}>
              View report
            </Button>
          )}
        </Centered>
      );
    }
    // Clean completion → the effect above auto-redirects to the report (D1/D10). Show a brief
    // "Analysis complete ✓" flourish during the hold.
    return (
      <Centered>
        <CheckCircle2 size={48} className="text-risk-low" />
        <h2 className="text-h2 font-bold">Analysis complete</h2>
        <p className="text-body text-text-secondary">Taking you to your report…</p>
      </Centered>
    );
  }

  // ── running / connecting ──────────────────────────────────────────────────
  const hasStep = state.index != null && state.total != null && state.total > 0;
  const pct = hasStep ? Math.round((state.index! / state.total!) * 100) : 0;
  return (
    <Centered>
      <ProcessingArt />
      <div className="reveal max-w-lg text-center">
        <h2 className="font-display text-h1 font-semibold text-text-primary">
          Analyzing your contract…
        </h2>
        <p className="mt-2 text-body text-text-secondary">
          Our 7-agent pipeline is reading every clause. This usually takes under 2 minutes.
        </p>
      </div>

      <div className="glass gloss reveal w-full max-w-xl rounded-card p-5 text-left">
        <div className="mb-3 flex items-center justify-between gap-4">
          <span className="min-w-0 truncate text-body font-medium text-text-primary">
            {hasStep && (
              <span className="text-text-tertiary">
                Step {state.index} of {state.total} ·{" "}
              </span>
            )}
            {state.phase === "connecting" ? "Starting analysis…" : nodeLabel(state.node)}
          </span>
          <span className="shrink-0 text-body font-semibold text-text-primary tabular-nums">
            {pct}%
          </span>
        </div>

        <ProgressBar value={pct} />

        {/* Stage chips — the real 7-agent pipeline, with done / active / upcoming states. */}
        <ul className="mt-5 flex flex-wrap gap-2">
          {STAGES.map(({ idx, label }) => {
            const st = chipState(idx, state.index);
            return (
              <li
                key={idx}
                className={`inline-flex items-center gap-1.5 rounded-pill border px-3 py-1 text-small font-medium ${
                  st === "done"
                    ? "border-risk-low/40 bg-risk-low/15 text-risk-low"
                    : st === "active"
                      ? "border-accent/50 bg-accent/15 text-text-primary"
                      : "border-white/10 bg-white/5 text-text-tertiary"
                }`}
              >
                {st === "done" ? (
                  <CheckCircle2 size={13} />
                ) : st === "active" ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : null}
                {label}
              </li>
            );
          })}
        </ul>
      </div>

      <p className="flex items-center gap-2 text-small text-text-tertiary">
        <Lock size={13} className="text-accent" />
        Navigation is paused until the analysis finishes — you&apos;ll be taken to your report
        automatically.
      </p>
    </Centered>
  );
}

// The 7-agent pipeline as short stage labels (mirrors jobProgress NODE_INDEX order). Each chip's
// state is derived from the live step index: past = done, current = active, later = upcoming.
const STAGES: { idx: number; label: string }[] = [
  { idx: 1, label: "Ingesting" },
  { idx: 2, label: "Clauses" },
  { idx: 3, label: "Evidence" },
  { idx: 4, label: "Validating" },
  { idx: 5, label: "Scoring" },
  { idx: 6, label: "Redlining" },
  { idx: 7, label: "Report" },
];

function chipState(idx: number, currentIndex?: number | null): "done" | "active" | "upcoming" {
  if (currentIndex == null) return "upcoming";
  if (idx < currentIndex) return "done";
  if (idx === currentIndex) return "active";
  return "upcoming";
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-[calc(100vh-0px)] flex-col items-center justify-center gap-4 p-6 text-center">
      {children}
    </div>
  );
}
