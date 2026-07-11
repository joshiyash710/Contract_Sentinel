import { describe, test, expect } from "vitest";
import { validateFile, MAX_UPLOAD_BYTES } from "@/lib/upload";

function fileOfSize(name: string, size: number): File {
  const f = new File(["x"], name);
  Object.defineProperty(f, "size", { value: size });
  return f;
}

describe("validateFile (spec D1)", () => {
  test("accepts_pdf_and_docx", () => {
    expect(validateFile(fileOfSize("contract.pdf", 1000)).ok).toBe(true);
    expect(validateFile(fileOfSize("contract.docx", 1000)).ok).toBe(true);
    expect(validateFile(fileOfSize("CONTRACT.PDF", 1000)).ok).toBe(true); // case-insensitive
  });

  test("rejects_other_extension", () => {
    const r = validateFile(fileOfSize("contract.txt", 1000));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toBe("type");
    expect(validateFile(fileOfSize("img.png", 1000)).ok).toBe(false);
  });

  test("rejects_empty", () => {
    const r = validateFile(fileOfSize("contract.pdf", 0));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toBe("empty");
  });

  test("rejects_oversize", () => {
    const r = validateFile(fileOfSize("contract.pdf", MAX_UPLOAD_BYTES + 1));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toBe("size");
  });
});
