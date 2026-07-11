import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { getApiClient } from "@/lib/api/provider";
import { ApiError } from "@/lib/api/client";
import { UploadForm } from "@/components/upload/UploadForm";
import { makeFakeClient } from "./_fakeClient";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }));

function fileOf(name: string, size = 1000): File {
  const f = new File(["x"], name);
  Object.defineProperty(f, "size", { value: size });
  return f;
}
function selectFile(file: File) {
  const input = screen.getByTestId("file-input") as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
}

beforeEach(() => {
  push.mockReset();
  vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ accepted: { job_id: "job-xyz", status: "queued", submitted_at: "t" } }));
});

describe("UploadForm (spec AC-1..AC-8, EC-3/EC-4)", () => {
  test("renders_stepper_and_zone", () => {
    render(<UploadForm />);
    expect(screen.getByRole("heading", { name: /upload new contract/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /browse files/i })).toBeInTheDocument();
    expect(screen.getByText("PDF")).toBeInTheDocument();
    expect(screen.getByText("DOCX")).toBeInTheDocument();
    expect(screen.queryByText("TXT")).toBeNull();
    // Stepper: exactly one current step, and it is "Upload"
    const current = screen.getAllByRole("listitem").filter((li) => li.getAttribute("data-state") === "current");
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("Upload");
  });

  test("valid_file_submits_and_navigates", async () => {
    render(<UploadForm />);
    selectFile(fileOf("contract.pdf"));
    await waitFor(() => expect(getApiClient().submitAnalysis).toHaveBeenCalledTimes(1));
    expect(push).toHaveBeenCalledWith("/jobs/job-xyz");
  });

  test("drop_behaves_like_browse", async () => {
    render(<UploadForm />);
    const zone = screen.getByTestId("dropzone");
    fireEvent.drop(zone, { dataTransfer: { files: [fileOf("c.docx")] } });
    await waitFor(() => expect(push).toHaveBeenCalledWith("/jobs/job-xyz"));
  });

  test("invalid_type_blocks_submit", async () => {
    render(<UploadForm />);
    selectFile(fileOf("notes.txt"));
    expect(await screen.findByText(/only pdf and docx/i)).toBeInTheDocument();
    expect(getApiClient().submitAnalysis).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  test("oversize_blocks_submit", async () => {
    render(<UploadForm />);
    selectFile(fileOf("big.pdf", 26 * 1024 * 1024));
    expect(await screen.findByText(/25 mb/i)).toBeInTheDocument();
    expect(getApiClient().submitAnalysis).not.toHaveBeenCalled();
  });

  test("empty_blocks_submit", async () => {
    render(<UploadForm />);
    selectFile(fileOf("empty.pdf", 0));
    expect(await screen.findByText(/empty/i)).toBeInTheDocument();
    expect(getApiClient().submitAnalysis).not.toHaveBeenCalled();
  });

  test("busy_state_prevents_double_submit", async () => {
    const fake = makeFakeClient({});
    (fake.submitAnalysis as unknown as ReturnType<typeof vi.fn>).mockImplementation(() => new Promise(() => {}));
    vi.mocked(getApiClient).mockReturnValue(fake);
    render(<UploadForm />);
    selectFile(fileOf("a.pdf"));
    await waitFor(() => expect(screen.getByRole("button", { name: /browse files/i })).toBeDisabled());
    selectFile(fileOf("b.pdf"));
    expect(fake.submitAnalysis).toHaveBeenCalledTimes(1); // second ignored
  });

  test("no_external_or_recipient_ui", () => {
    render(<UploadForm />);
    expect(screen.queryByText(/google drive/i)).toBeNull();
    expect(screen.queryByText(/dropbox/i)).toBeNull();
    expect(screen.queryByText(/connect/i)).toBeNull();
    expect(screen.queryByPlaceholderText(/email/i)).toBeNull();
  });

  test("submit_network_error_inline", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ submitError: new ApiError("net") }));
    render(<UploadForm />);
    selectFile(fileOf("a.pdf"));
    expect(await screen.findByText(/couldn.t reach the server/i)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  test("submit_400_and_413_mapped", async () => {
    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ submitError: new ApiError("bad", 400) }));
    const { unmount } = render(<UploadForm />);
    selectFile(fileOf("a.pdf"));
    expect(await screen.findByText(/unsupported or empty/i)).toBeInTheDocument();
    unmount();

    vi.mocked(getApiClient).mockReturnValue(makeFakeClient({ submitError: new ApiError("big", 413) }));
    render(<UploadForm />);
    selectFile(fileOf("a.pdf"));
    expect(await screen.findByText(/too large/i)).toBeInTheDocument();
  });
});
