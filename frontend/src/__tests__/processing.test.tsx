import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { ProcessingView } from "@/components/processing/ProcessingView";
import { makeFakeClient, progress, terminal, completedFinal } from "./_fakeClient";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));

beforeEach(() => {
  push.mockReset();
  vi.mocked(getApiClient).mockReset();
});

describe("ProcessingView (spec AC-9..AC-15, EC-1/2/6/8)", () => {
  test("renders_connecting_before_first_event", () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ events: [] }));
    render(<ProcessingView jobId="job-1" />);
    expect(screen.getByText(/starting analysis/i)).toBeInTheDocument();
  });

  test("renders_progress", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ events: [progress("clause_splitter", 2, 4)] }));
    render(<ProcessingView jobId="job-1" />);
    expect(await screen.findByText(/breaking the document into clauses/i)).toBeInTheDocument();
    expect(screen.getByText(/step 2 of 4/i)).toBeInTheDocument();
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "50");
  });

  test("unknown_node_generic_label", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ events: [progress("nope", 1, 4)] }));
    render(<ProcessingView jobId="job-1" />);
    expect(await screen.findByText("Analyzing…")).toBeInTheDocument();
  });

  test("completed_shows_report_link", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ events: [terminal("completed", completedFinal({ report_available: true }))] }),
    );
    render(<ProcessingView jobId="job-1" />);
    expect(await screen.findByText(/analysis complete/i)).toBeInTheDocument();
    const md = screen.getByRole("link", { name: /view report/i });
    expect(md).toHaveAttribute("href", "/api/jobs/job-1/report?format=md");
    expect(screen.getByRole("link", { name: /view json/i })).toHaveAttribute(
      "href",
      "/api/jobs/job-1/report?format=json",
    );
  });

  test("ingest_error_soft_state", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({
        events: [terminal("completed", completedFinal({ report_available: false, error: { kind: "ingest_error", message: "corrupt pdf" } }))],
      }),
    );
    render(<ProcessingView jobId="job-1" />);
    expect(await screen.findByText(/corrupt pdf/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /view report/i })).toBeNull();
  });

  test("failed_shows_retry", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ events: [terminal("failed", completedFinal({ status: "failed" }))] }),
    );
    render(<ProcessingView jobId="job-1" />);
    const retry = await screen.findByRole("button", { name: /retry/i });
    fireEvent.click(retry);
    expect(push).toHaveBeenCalledWith("/upload");
  });

  test("already_finished_lands_terminal", async () => {
    vi.mocked(getApiClient).mockReturnValue(
      makeFakeClient({ events: [terminal("completed", completedFinal())] }),
    );
    render(<ProcessingView jobId="job-1" />);
    expect(await screen.findByText(/analysis complete/i)).toBeInTheDocument();
  });

  test("error_phase_refresh_reconnects", async () => {
    const fake = makeFakeClient({ emitError: true });
    vi.mocked(getApiClient).mockReturnValue(fake);
    render(<ProcessingView jobId="job-1" />);
    const refresh = await screen.findByRole("button", { name: /refresh/i });
    expect(fake.openJobEvents).toHaveBeenCalledTimes(1);
    fireEvent.click(refresh);
    await waitFor(() => expect(fake.openJobEvents).toHaveBeenCalledTimes(2));
  });
});
