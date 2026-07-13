import type { ReportFinding } from "@/lib/api/types";

/** "limitation_of_liability" → "Limitation Of Liability" (snake/space separated → Title Case). */
export function titleCase(s: string): string {
  return s
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

/**
 * Card title (spec 017 D3): the clause_type title-cased, or "Clause {position}" as a fallback.
 * `position` is rendered VERBATIM (not re-indexed) so the card numbering matches the backend's
 * own Markdown "## Finding {position}".
 */
export function findingTitle(f: ReportFinding): string {
  if (f.clause_type) return titleCase(f.clause_type);
  return `Clause ${f.position}`;
}

/** Human-friendly generated-at; tolerant of bad input (never throws — spec EC-6 spirit). */
export function formatGeneratedAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
