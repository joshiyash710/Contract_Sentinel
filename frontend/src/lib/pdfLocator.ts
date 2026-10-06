/**
 * Feature 057 — pure geometry helper for the PDF click-to-highlight overlay.
 *
 * 055 captures each clause's `source_locator.spans[].bbox` as `[x0, y0, x1, y1]` in PDF points
 * (PyMuPDF `get_text("dict")` origin = top-left). react-pdf's rendered `<Page>` viewport is also
 * top-left after the default transform, so a bbox maps to a pixel rect by a single `scale` multiply.
 * Kept pure (no pdf.js) so it is unit-testable without a browser/worker.
 */

export interface HighlightRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Convert a PDF-point bbox `[x0,y0,x1,y1]` + the page's render `scale` → a CSS pixel rect. */
export function bboxToRect(bbox: number[], scale: number): HighlightRect {
  const [x0, y0, x1, y1] = bbox;
  return {
    left: x0 * scale,
    top: y0 * scale,
    width: (x1 - x0) * scale,
    height: (y1 - y0) * scale,
  };
}
