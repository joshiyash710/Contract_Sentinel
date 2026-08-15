"""Fetch the CUAD dataset (Contract Understanding Atticus Dataset, CC BY 4.0) for feature 041.

Downloads the canonical Zenodo release into the GITIGNORED raw dir
``data/kb/sources/cuad_raw/`` and extracts it, so ``scripts/build_corpus.py`` can curate a corpus
slice from ``CUAD_v1/CUAD_v1.json``. Idempotent: if the extracted JSON is already present it prints a
notice and exits 0. Network-only — never run in the pytest suite.

CUAD is licensed CC BY 4.0 (The Atticus Project). Attribution is recorded in
``data/kb/SOURCES.md``. Only a curated, license-permitted slice is committed to the repo; this raw
download is reproducible and gitignored.

Usage (from backend/, online):

    python scripts/fetch_cuad.py
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from urllib.request import urlopen

BACKEND_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BACKEND_DIR / "data" / "kb" / "sources" / "cuad_raw"
ZIP_PATH = RAW_DIR / "CUAD_v1.zip"
EXTRACTED_JSON = RAW_DIR / "CUAD_v1" / "CUAD_v1.json"
CUAD_URL = "https://zenodo.org/records/4595826/files/CUAD_v1.zip?download=1"


def _download(url: str, dest: Path) -> None:
    print(f"Downloading CUAD (~101 MB) from {url} ...")
    with urlopen(url) as resp, dest.open("wb") as fh:  # noqa: S310 (trusted Zenodo URL)
        total = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            total += len(chunk)
            print(f"\r  {total / 1_048_576:.1f} MB", end="", flush=True)
    print()


def main() -> int:
    if EXTRACTED_JSON.exists():
        print(f"CUAD already present at {EXTRACTED_JSON.relative_to(BACKEND_DIR)} — nothing to do.")
        return 0

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if not ZIP_PATH.exists():
            _download(CUAD_URL, ZIP_PATH)
        print(f"Extracting {ZIP_PATH.name} ...")
        with zipfile.ZipFile(ZIP_PATH) as zf:
            zf.extractall(RAW_DIR)
    except Exception as exc:  # noqa: BLE001 — offline / transient failure is tolerated (spec EC-1)
        print(
            f"\nCould not fetch CUAD ({exc}). This is non-fatal: build_corpus.py falls back to the "
            "committed Bonterms corpus. Re-run when online.",
            file=sys.stderr,
        )
        return 0

    if EXTRACTED_JSON.exists():
        print(f"CUAD ready: {EXTRACTED_JSON.relative_to(BACKEND_DIR)}")
    else:
        print("Extraction finished but CUAD_v1.json was not found — check the archive.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
