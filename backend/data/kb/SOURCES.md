# CRAG Knowledge-Base — Source Provenance & Licenses

The local clause knowledge base (`clauses_corpus.jsonl` → `clauses.faiss` + `clauses_meta.jsonl`) is
built by `scripts/build_corpus.py` → `scripts/build_kb.py` from the sources below. Every committed
corpus record retains its `source_reference`; feature-041 (CUAD) records additionally carry
`clause_type` and `source_license` metadata.

Only **license-permitted** text is committed to this repository. Bulk raw datasets are **not**
committed — they are reproducible via the fetch scripts and are gitignored under
`data/kb/sources/`.

| Source | Content | License | Retrieved | How it's included |
|---|---|---|---|---|
| **Bonterms Cloud Terms v1.0** | Standardized cloud-services agreement | Free to use (Bonterms Standard Terms; see the document footer) | 2025 (repo inception) | Curated markdown in `app/db/Cloud-Terms.md`; parsed into clause snippets. |
| **Bonterms DPA v1.0** | Data Protection Addendum | Free to use (Bonterms) | 2025 (repo inception) | Curated markdown in `app/db/Data-Protection-Addendum.md`. |
| **CUAD v1** (Contract Understanding Atticus Dataset) | 510 real commercial contracts with expert clause-span annotations across 41 categories | **CC BY 4.0** | 2026-08-15 | Downloaded via `scripts/fetch_cuad.py` (Zenodo). A curated, per-category-capped, de-duplicated **slice** of annotated spans is embedded as reference clauses, each tagged with its `clause_type` (the CUAD category) and `source_license`. |

## Attribution (required)

**CUAD** — *"CUAD: An Expert-Annotated NLP Dataset for Legal Contract Review"*, Dan Hendrycks, Collin
Burns, Anya Chen, Spencer Ball (The Atticus Project, 2021). Licensed under
**Creative Commons Attribution 4.0 International (CC BY 4.0)** —
<https://creativecommons.org/licenses/by/4.0/>. Dataset:
<https://www.atticusprojectai.org/cuad> · <https://zenodo.org/records/4595826>.

Use of CUAD-derived clause text in this project is under CC BY 4.0; this file provides the required
attribution. No CUAD text beyond the license-permitted curated slice is redistributed here.

## Reproducing the corpus

```bash
# from backend/, with Ollama running and the bge-m3 embedding model pulled
python scripts/fetch_cuad.py       # downloads CUAD → data/kb/sources/cuad_raw/ (gitignored)
python scripts/build_corpus.py     # Bonterms + curated CUAD slice → data/kb/clauses_corpus.jsonl
python scripts/build_kb.py         # embeds (bge-m3) → clauses.faiss + clauses_meta.jsonl
```

If the CUAD raw fetch is absent (offline), `build_corpus.py` degrades gracefully to the Bonterms-only
corpus.

## Honesty note

The corpus is diverse and license-clean but finite. Retrieval quality and any accuracy numbers
measured against it (see `backend/eval/`) are only as good as this corpus; the eval labels are
best-effort and **not** lawyer-reviewed.
