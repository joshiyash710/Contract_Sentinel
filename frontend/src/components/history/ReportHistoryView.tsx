"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Plus, FileText, ArrowUpRight, ChevronLeft, ChevronRight } from "lucide-react";
import { useJobs } from "@/lib/useJobs";
import type { JobListItem } from "@/lib/api/types";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { SearchInput } from "@/components/ui/SearchInput";
import { StatusBadge, type BadgeTone } from "@/components/ui/StatusBadge";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { formatSubmitted, riskTone, overflowNote } from "@/lib/history";

// Fetch the most-recent 100 (backend JOBS_LIST_MAX_LIMIT clamp) in one call, then search / sort /
// paginate client-side over the retention-bounded set (spec D2). Do NOT import backend config.
const FETCH_LIMIT = 100;
const PAGE_SIZE = 20;

// DataTable constrains its generic to Record<string, unknown>; JobListItem (an interface) lacks
// an implicit index signature, so widen it here for the table without touching the primitive.
type HistoryRow = JobListItem & Record<string, unknown>;

const STATUS_TONE: Record<string, BadgeTone> = {
  completed: "success",
  running: "neutral",
  queued: "neutral",
  failed: "danger",
};

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function ReportHistoryView() {
  const { state, retry } = useJobs({ limit: FETCH_LIMIT });
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);

  const items = useMemo(() => state.data?.items ?? [], [state.data]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter((i) => i.original_filename.toLowerCase().includes(q));
  }, [items, search]);

  if (state.phase === "loading") return <Centered>Loading your contracts…</Centered>;
  if (state.phase === "error")
    return (
      <Centered>
        <p className="text-text-secondary">{state.message ?? "We couldn't load your contracts."}</p>
        <Button variant="primary" onClick={retry}>
          Try again
        </Button>
      </Centered>
    );
  if (state.phase === "empty") return <EmptyHistory />;

  const total = state.data?.total ?? items.length;
  const note = overflowNote(items.length, total);

  // Client-side pagination over the filtered set (DataTable has no pager — plan §6).
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const clampedPage = Math.min(page, pageCount - 1);
  const start = clampedPage * PAGE_SIZE;
  const pageRows = filtered.slice(start, start + PAGE_SIZE);
  const showPager = filtered.length > PAGE_SIZE;

  const onSearch = (v: string) => {
    setSearch(v);
    setPage(0);
  };

  const columns: Column<HistoryRow>[] = [
    {
      key: "original_filename",
      header: "Contract",
      sortable: true,
      render: (row) =>
        row.report_available ? (
          <Link
            href={`/jobs/${row.job_id}/report`}
            title={row.original_filename}
            className="block max-w-[22rem] truncate font-medium text-text-primary hover:text-accent"
          >
            {row.original_filename}
          </Link>
        ) : (
          <span
            title={row.original_filename}
            className="block max-w-[22rem] truncate font-medium text-text-primary"
          >
            {row.original_filename}
          </span>
        ),
    },
    {
      key: "submitted_at",
      header: "Submitted",
      sortable: true,
      render: (row) => (
        <span className="whitespace-nowrap text-text-secondary">
          {formatSubmitted(row.submitted_at)}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (row) => (
        <StatusBadge label={cap(row.status)} tone={STATUS_TONE[row.status] ?? "neutral"} />
      ),
    },
    {
      key: "risk_band",
      header: "Risk",
      render: (row) =>
        row.status === "completed" && row.risk_band ? (
          <StatusBadge label={cap(row.risk_band)} tone={riskTone(row.risk_band)} />
        ) : (
          <span className="text-text-tertiary">—</span>
        ),
    },
    {
      key: "findings",
      header: "Findings",
      render: (row) =>
        row.status === "completed" ? (
          <span className="whitespace-nowrap tabular-nums text-text-secondary">
            H {row.high ?? 0} · M {row.medium ?? 0} · L {row.low ?? 0}
          </span>
        ) : (
          <span className="text-text-tertiary">—</span>
        ),
    },
  ];

  const rowAction = (row: HistoryRow) => {
    if (row.report_available)
      return (
        <Link
          href={`/jobs/${row.job_id}/report`}
          className="inline-flex items-center gap-1 text-small font-medium text-accent hover:underline"
        >
          View Report <ArrowUpRight size={14} />
        </Link>
      );
    const hint =
      row.status === "failed"
        ? "Failed"
        : row.status === "completed"
          ? "No report"
          : "Processing…";
    return <span className="text-small text-text-tertiary">{hint}</span>;
  };

  return (
    <div className="p-6">
      {/* Header */}
      <div className="relative mb-6 overflow-hidden rounded-card border border-subtle bg-card-raised p-6">
        <div className="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full bg-accent-gradient opacity-10 blur-3xl" />
        <div className="relative flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-page-title text-text-primary">Report History</h1>
            <p className="mt-1 text-body text-text-secondary">
              Every contract you&apos;ve analyzed, newest first.
            </p>
          </div>
          <Link href="/upload">
            <Button variant="primary" className="shrink-0">
              <Plus size={16} /> Upload New Contract
            </Button>
          </Link>
        </div>
      </div>

      {/* Controls */}
      <div className="mb-4 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <SearchInput
          aria-label="Search contracts"
          placeholder="Search contracts by filename…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          className="w-full md:max-w-sm"
        />
        {note && <span className="text-small text-text-tertiary">{note}</span>}
      </div>

      {/* Table */}
      <Card className="overflow-hidden p-0">
        {filtered.length === 0 ? (
          <p className="py-14 text-center text-body text-text-secondary">
            No contracts match “{search.trim()}”.
          </p>
        ) : (
          <DataTable<HistoryRow>
            columns={columns}
            rows={pageRows as HistoryRow[]}
            actions={rowAction}
            rowKey={(r) => r.job_id}
          />
        )}
      </Card>

      {/* Pager */}
      {showPager && (
        <div className="mt-4 flex items-center justify-between text-small text-text-secondary">
          <span className="tabular-nums">
            {start + 1}–{Math.min(start + PAGE_SIZE, filtered.length)} of {filtered.length}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={clampedPage === 0}
            >
              <ChevronLeft size={16} /> Prev
            </Button>
            <Button
              variant="secondary"
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              disabled={clampedPage >= pageCount - 1}
            >
              Next <ChevronRight size={16} />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function EmptyHistory() {
  return (
    <Centered>
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-accent-gradient text-accent-fg shadow-glow">
        <FileText size={30} />
      </div>
      <h2 className="text-h2 font-bold">No contracts yet</h2>
      <p className="max-w-md text-body text-text-secondary">
        Your analyzed contracts will appear here. Upload your first contract to get started.
      </p>
      <Link
        href="/upload"
        className="mt-2 inline-flex items-center gap-2 rounded-lg bg-accent-gradient px-6 py-3 text-body font-semibold text-accent-fg shadow-glow transition hover:opacity-95"
      >
        <Plus size={16} /> Upload your first contract
      </Link>
    </Centered>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-6 text-center">
      {children}
    </div>
  );
}
