import { describe, test, expect } from "vitest";
import { bboxToRect } from "@/lib/pdfLocator";
import { realClient } from "@/lib/api/realProvider";

// Feature 057 — pure geometry helper (AC-4) + provider source URL (AC-1).

describe("bboxToRect (AC-4)", () => {
  test("scales a PDF-point bbox into a pixel rect", () => {
    expect(bboxToRect([10, 20, 30, 50], 2)).toEqual({ left: 20, top: 40, width: 40, height: 60 });
  });
  test("scale 1 maps points directly to pixels", () => {
    expect(bboxToRect([0, 0, 100, 40], 1)).toEqual({ left: 0, top: 0, width: 100, height: 40 });
  });
});

describe("getSourceUrl (AC-1)", () => {
  test("realProvider builds the 056 /source URL", () => {
    expect(realClient.getSourceUrl("job-1")).toMatch(/\/api\/jobs\/job-1\/source$/);
  });
});
