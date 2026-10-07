# RESULTS — Feature 055 Task 12: PDF extraction-diff measurement

Gating measurement for the feature-060 default-flip of `PDF_SOURCE_LOCATOR_ENABLED` (055) and
`UPLOAD_SOURCE_RETENTION_ENABLED` (056). 055/056/057 all shipped the chain flags OFF and deferred the
default-flip to "a separate change after the 055 extraction-diff measurement (055 Task 12)". This is that
measurement.

## Question (055 OQ-2)
When `PDF_SOURCE_LOCATOR_ENABLED` is ON, `pdf_parser` builds `extracted_text` from a `get_text("dict")` pass
(`_extract_text_with_spans`) instead of the plain `"\n".join(page.get_text())` path. Does the dict-built text
diverge from the plain text enough to change extraction or clause segmentation? If so, flipping the default
on could degrade accuracy.

## Method
`backend/eval/measure_055_extraction_diff.py`, run from `backend/`:

```
.venv/Scripts/python.exe -X utf8 eval/measure_055_extraction_diff.py
```

For each PDF in `backend/eval/corpus` (n = 30 real CUAD contracts) it compares, per document:
- **raw char similarity** — `difflib.SequenceMatcher(None, plain, dict_text).ratio()`
- **whitespace-collapsed similarity** — the same ratio after `" ".join(s.split())` on both (isolates pure
  spacing differences)
- **length delta** — `len(dict_text) - len(plain)`
- **clause-count drift** — `len(split_by_regex(plain))` vs `len(split_by_regex(dict_text))`

The two text builders are the production functions themselves: `_extract_text_with_spans` (dict path) and
`"\n".join(page.get_text() for page in doc)` (plain path).

## Result (n = 30)

| Metric | Value |
|---|---|
| raw char similarity | mean 99.97%, median 99.98%, **min 99.71%** |
| whitespace-collapsed similarity | **100.00%** on every document |
| length delta | −3 … −110 chars (dict path drops a few spaces at some span boundaries) |
| regex clause-count change | **0 / 30** documents |

## Conclusion
The dict path is **content-identical** to the plain path — the only differences are a handful of whitespace
characters at span boundaries (whitespace-collapsed similarity is 100% on every document), and clause
segmentation is **unchanged** (0/30 clause-count drift). Flipping `PDF_SOURCE_LOCATOR_ENABLED` (and, paired
with it, `UPLOAD_SOURCE_RETENTION_ENABLED`) on by default is therefore safe. Implemented in **feature 060**.
