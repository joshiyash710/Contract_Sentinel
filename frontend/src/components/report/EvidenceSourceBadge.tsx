import { Database, Globe } from "lucide-react";
import { StatusBadge, type BadgeTone } from "@/components/ui/StatusBadge";

/**
 * Feature 058 — evidence-source badge. Surfaces CRAG's per-clause retrieval decision
 * (009 ReportFinding.path_taken) so a reader can see whether a finding was judged against the
 * curated local legal KB or a live web search. Pure presentation of an existing field — it never
 * recomputes the source (the KB-vs-web routing stays CRAG's; constitution §2/§3).
 */

// Closed map: ONLY the two real RetrievalPath values (backend/app/graph/state.py). Anything else —
// null, "", or a future/stale value — is "unknown" and renders nothing (spec D2/AC-3/AC-4).
const SOURCE_META: Record<
  string,
  { label: string; tone: BadgeTone; Icon: typeof Database }
> = {
  local_kb: { label: "Local knowledge base", tone: "success", Icon: Database }, // trusted source (D7/D8)
  web_fallback: { label: "Live web search", tone: "warning", Icon: Globe }, // lower-trust source (D7/D8)
};

/** The user-facing source label, or null for a null/unknown path (D2). Shared with the
 *  FindingCard "Supporting sources" section label (AC-10) so the two cannot drift. */
export function evidenceSourceLabel(path?: string | null): string | null {
  return (path && SOURCE_META[path]?.label) || null;
}

/**
 * Header badge: a lucide icon + a themed StatusBadge pill (D3 — reuses the design-system primitive;
 * the icon is composed adjacent since StatusBadge has no icon slot). Renders nothing when the source
 * is null/unknown (D2) — mirroring FindingRiskBadge's safe-fallback behavior. Tones come from theme
 * tokens (no raw hex, AC-7).
 */
export function EvidenceSourceBadge({ path }: { path?: string | null }) {
  const meta = path ? SOURCE_META[path] : undefined;
  if (!meta) return null;
  const { label, tone, Icon } = meta;
  return (
    <span
      data-testid="evidence-source-badge"
      className="inline-flex shrink-0 items-center gap-1.5"
    >
      <Icon size={13} aria-hidden className="text-text-tertiary" />
      <StatusBadge label={label} tone={tone} />
    </span>
  );
}
