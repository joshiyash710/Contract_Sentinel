/* eslint-disable react-hooks/exhaustive-deps -- the react-pdf mock's mount-once effect intentionally
   omits deps; this is test-mock scaffolding, not app code. */
import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// Feature 057 — ContractViewer loads the source from getSourceUrl (AC-5) and degrades gracefully (AC-6).
// pdf.js can't run in jsdom, so react-pdf is mocked; a hoisted flag toggles the load-success/error path.

const h = vi.hoisted(() => ({ fails: false }));

vi.mock("react-pdf", async () => {
  const React = (await vi.importActual("react")) as typeof import("react");
  return {
    pdfjs: { GlobalWorkerOptions: {} },
    Document: ({ file, children, onLoadSuccess, onLoadError }: any) => {
      React.useEffect(() => {
        if (h.fails) onLoadError?.(new Error("boom"));
        else onLoadSuccess?.({ numPages: 1 });
      }, []);
      return React.createElement("div", { "data-testid": "pdf-document", "data-file": file }, children);
    },
    Page: ({ pageNumber }: any) =>
      React.createElement("div", { "data-testid": "pdf-page", "data-page": pageNumber }),
  };
});

vi.mock("@/lib/api/provider", () => ({
  getApiClient: () => ({ getSourceUrl: (id: string) => `/api/jobs/${id}/source` }),
}));

import { ContractViewer } from "@/components/report/ContractViewer";

beforeEach(() => {
  h.fails = false;
  Element.prototype.scrollIntoView = vi.fn(); // jsdom lacks it (mirrors report.test.tsx)
});

const LOCATOR = { pages: [1], spans: [{ page: 1, bbox: [10, 20, 100, 60] }] };

describe("ContractViewer (feature 057)", () => {
  test("loads the PDF from getSourceUrl and overlays a highlight (AC-5)", async () => {
    render(<ContractViewer jobId="job-1" locator={LOCATOR} open onClose={vi.fn()} />);
    const doc = await screen.findByTestId("pdf-document");
    expect(doc.getAttribute("data-file")).toBe("/api/jobs/job-1/source");
    await waitFor(() => expect(screen.getByTestId("clause-highlight")).toBeInTheDocument());
  });

  test("shows a placeholder when the source fails to load (AC-6)", async () => {
    h.fails = true;
    render(<ContractViewer jobId="job-1" locator={null} open onClose={vi.fn()} />);
    expect(await screen.findByText(/isn.t available/i)).toBeInTheDocument();
    expect(screen.queryByTestId("pdf-page")).not.toBeInTheDocument();
  });

  test("renders nothing when closed", () => {
    render(<ContractViewer jobId="job-1" locator={null} open={false} onClose={vi.fn()} />);
    expect(screen.queryByTestId("contract-viewer")).not.toBeInTheDocument();
  });
});
