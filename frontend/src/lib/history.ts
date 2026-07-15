import type { BadgeTone } from "@/components/ui/StatusBadge";

/**
 * Pure row-formatting helpers for the Report History list (feature 021). No React, no data
 * fetching — kept unit-friendly so `ReportHistoryView` stays lean (plan §3.2).
 */

/** Short, human date/time for the Submitted column. Falls back to the raw string if unparseable. */
export function formatSubmitted(iso: string): string {
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

/** Maps a JobListItem.risk_band ("high"|"medium"|"low"|"none") to a StatusBadge tone. */
export function riskTone(band?: string | null): BadgeTone {
  switch (band) {
    case "high":
      return "danger";
    case "medium":
      return "warning";
    case "low":
      return "success";
    default:
      return "neutral";
  }
}

/**
 * Honest overflow note (D2/EC-6): when the server holds more jobs than we fetched, tell the user
 * exactly how many are shown. Returns null when everything fetched fits.
 */
export function overflowNote(fetched: number, total: number): string | null {
  return total > fetched ? `Showing the most recent ${fetched} of ${total}.` : null;
}
