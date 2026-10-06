"use client";

import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { X } from "lucide-react";
import { getApiClient } from "@/lib/api/provider";
import { bboxToRect } from "@/lib/pdfLocator";

// pdf.js worker (feature 057). Primary: resolve the bundled worker via import.meta.url (works with the
// Next bundler). If a deploy can't resolve it, pin a matching-version CDN worker instead. This module is
// only ever loaded client-side (AnalysisWorkspace imports it via dynamic(..., { ssr: false })).
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

// Fixed render scale: at scale S, 1 PDF point = S pixels, so a 055 bbox (points) maps to a pixel rect
// via bboxToRect(bbox, S) with no viewport math.
const SCALE = 1.5;

export type ViewerLocator = {
  pages: number[];
  spans: { page: number; bbox: number[] }[];
} | null;

/**
 * Feature 057 — on-demand drawer that renders the original uploaded PDF (056 /source) and overlays the
 * 055 source_locator highlights for the selected finding. Client-only (pdf.js). Degrades to a placeholder
 * when the source can't be loaded; renders nothing when closed.
 */
export function ContractViewer({
  jobId,
  locator,
  open,
  onClose,
}: {
  jobId: string;
  locator: ViewerLocator;
  open: boolean;
  onClose: () => void;
}) {
  const [numPages, setNumPages] = useState(0);
  const [error, setError] = useState(false);
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const fileUrl = getApiClient().getSourceUrl(jobId);

  // Close on Escape while open.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Jump to the clause's first page when the selection changes (once the doc is loaded).
  const targetPage = locator?.pages?.[0];
  useEffect(() => {
    if (!open || !targetPage || !numPages) return;
    pageRefs.current[targetPage]?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [open, targetPage, numPages]);

  if (!open) return null;

  return (
    <div
      data-testid="contract-viewer"
      className="fixed inset-0 z-50 flex justify-end bg-black/50"
      onClick={onClose}
    >
      <div
        className="glass flex h-full w-full max-w-3xl flex-col overflow-hidden bg-card-raised shadow-[var(--glass-shadow)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-subtle p-4">
          <h2 className="font-display text-h3 font-semibold text-text-primary">Original contract</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close viewer"
            className="rounded-input p-1 text-text-tertiary hover:bg-white/5 hover:text-text-primary"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto bg-black/20 p-4">
          {error ? (
            <p className="mt-8 text-center text-body text-text-secondary">
              The original document isn&apos;t available.
            </p>
          ) : (
            <Document
              file={fileUrl}
              onLoadSuccess={({ numPages: n }) => setNumPages(n)}
              onLoadError={() => setError(true)}
              loading={<p className="mt-8 text-center text-small text-text-tertiary">Loading…</p>}
              error={
                <p className="mt-8 text-center text-body text-text-secondary">
                  The original document isn&apos;t available.
                </p>
              }
            >
              {Array.from({ length: numPages }, (_, i) => i + 1).map((n) => {
                const spans = (locator?.spans ?? []).filter((s) => s.page === n);
                return (
                  <div
                    key={n}
                    ref={(el) => {
                      pageRefs.current[n] = el;
                    }}
                    className="relative mx-auto mb-4 w-fit"
                  >
                    <Page
                      pageNumber={n}
                      scale={SCALE}
                      renderTextLayer={false}
                      renderAnnotationLayer={false}
                    />
                    {spans.map((s, idx) => {
                      const r = bboxToRect(s.bbox, SCALE);
                      return (
                        <div
                          key={idx}
                          data-testid="clause-highlight"
                          className="pointer-events-none absolute rounded-sm bg-accent/30 ring-1 ring-accent"
                          style={{ left: r.left, top: r.top, width: r.width, height: r.height }}
                        />
                      );
                    })}
                  </div>
                );
              })}
            </Document>
          )}
        </div>
      </div>
    </div>
  );
}
