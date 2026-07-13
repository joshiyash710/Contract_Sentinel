/** Brief "Analysis complete ✓" hold before the processing screen auto-redirects to the
 * report (spec 017 D10). A named constant so tests can mock it to 0 (see processing-redirect
 * test) rather than waiting on a real timer. */
export const REPORT_REDIRECT_DELAY_MS = 1200;
