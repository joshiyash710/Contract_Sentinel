import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { ReportView } from "@/components/report/ReportView";
import { makeFakeClient } from "./_fakeClient";
import { emptyReportFixture } from "@/lib/api/fixtures";

const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace }) }));
vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));

// jsdom has no scrollIntoView — the workspace calls it optional-chained; stub so it's a no-op.
beforeEach(() => {
  push.mockReset();
  replace.mockReset();
  vi.mocked(getApiClient).mockReset();
  Element.prototype.scrollIntoView = vi.fn();
});

const panel = () => screen.getByTestId("analysis-panel");
const nav = () => screen.getByTestId("clause-navigator");

/** The finding card whose header button matches `title`, scoped to the analysis panel. */
function cardByTitle(title: RegExp): HTMLElement {
  const header = within(panel()).getByRole("button", { name: title });
  return header.closest("[data-testid='finding-card']") as HTMLElement;
}

describe("Analysis Workspace (spec 022 AC-1,3,4,6,7,8,11)", () => {
  test("two_pane_layout_renders_navigator_and_panel", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({})); // reportFixture: 4 findings
    render(<ReportView jobId="job-1" />);

    await screen.findByTestId("analysis-panel");
    expect(nav()).toBeInTheDocument();
    // one nav entry + one card per finding
    expect(within(nav()).getAllByTestId("nav-clause")).toHaveLength(4);
    expect(within(panel()).getAllByTestId("finding-card")).toHaveLength(4);
  });

  test("navigator_lists_findings_in_order_with_locator", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportView jobId="job-1" />);

    await screen.findByTestId("clause-navigator");
    const entries = within(nav()).getAllByTestId("nav-clause");
    expect(entries.map((e) => e.textContent)).toEqual([
      expect.stringContaining("Limitation Of Liability"),
      expect.stringContaining("Indemnification"),
      expect.stringContaining("Governing Law"),
      expect.stringContaining("Clause 4"),
    ]);
    // section locator shown where present (finding 1 → § 3.1)
    expect(entries[0].textContent).toContain("3.1");
  });

  test("selecting_a_navigator_entry_focuses_and_expands_its_card", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportView jobId="job-1" />);

    await screen.findByTestId("clause-navigator");
    const entries = within(nav()).getAllByTestId("nav-clause");
    // finding 2 (Indemnification) starts collapsed (only finding 1 is default-open)
    const card2Header = () => within(panel()).getByRole("button", { name: /indemnification/i });
    expect(card2Header()).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(entries[1]);
    expect(entries[1]).toHaveAttribute("aria-current", "true");
    expect(card2Header()).toHaveAttribute("aria-expanded", "true");

    // selecting another entry moves the active state off #2
    fireEvent.click(entries[2]);
    expect(entries[2]).toHaveAttribute("aria-current", "true");
    expect(entries[1]).not.toHaveAttribute("aria-current", "true");
  });

  test("compare_shows_before_and_after_for_a_rewritten_clause", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportView jobId="job-1" />);

    await screen.findByTestId("analysis-panel");
    // finding 1 (rewritten) is default-open
    const card1 = cardByTitle(/limitation of liability/i);
    const compareBtn = within(card1).getByRole("button", { name: /compare/i });
    fireEvent.click(compareBtn);

    const compare = within(card1).getByTestId("clause-compare");
    // original clause text + suggested rewrite text both present in the side-by-side view
    expect(within(compare).getByText(/aggregate liability exceed the fees paid/i)).toBeInTheDocument();
    expect(
      within(compare).getByText(/aggregate liability shall not exceed the total fees/i),
    ).toBeInTheDocument();
  });

  test("no_compare_control_for_findings_without_a_rewrite", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportView jobId="job-1" />);

    await screen.findByTestId("analysis-panel");
    // finding 2 (unavailable) and finding 3 (not_eligible) — expand each, no Compare button
    fireEvent.click(within(panel()).getByRole("button", { name: /indemnification/i }));
    const card2 = cardByTitle(/indemnification/i);
    expect(within(card2).queryByRole("button", { name: /compare/i })).not.toBeInTheDocument();

    fireEvent.click(within(panel()).getByRole("button", { name: /governing law/i }));
    const card3 = cardByTitle(/governing law/i);
    expect(within(card3).queryByRole("button", { name: /compare/i })).not.toBeInTheDocument();
  });

  test("empty_report_shows_panel_empty_state_and_navigator_hint", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ report: emptyReportFixture }));
    render(<ReportView jobId="job-1" />);

    expect(await screen.findByText(/no risky clauses found/i)).toBeInTheDocument();
    expect(within(nav()).queryAllByTestId("nav-clause")).toHaveLength(0);
    expect(within(nav()).getByText(/no flagged clauses/i)).toBeInTheDocument();
  });

  test("no_legal_ai_assistant_chat_panel", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({}));
    render(<ReportView jobId="job-1" />);
    await screen.findByTestId("analysis-panel");

    expect(screen.queryByText(/legal ai assistant/i)).not.toBeInTheDocument();
    // no chat message input
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
