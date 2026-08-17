"""Run phase (feature 026): execute the REAL pipeline over the gold corpus and cache artifacts.

Needs live Ollama. Delivery is DISABLED at the import-bound target (safety-critical). Run from
`backend/`:  python -m eval.harness.run --gold eval/gold
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

# ── Disable delivery BEFORE importing the runner (patch the import-bound module name; setting
#    app.config.MCP_DELIVERY_ENABLED would be a no-op — delivery_step binds it at import). ──
import app.delivery.delivery_step as _dstep  # noqa: E402

_dstep.MCP_DELIVERY_ENABLED = False

from app.runner.core import run_pipeline  # noqa: E402
from eval.harness.schema import build_sidecar, load_gold_dir  # noqa: E402

_BACKEND = Path(__file__).resolve().parents[2]  # eval/harness/ → eval/ → backend/


def _resolve(doc: str) -> Path:
    p = Path(doc)
    return p if p.is_absolute() else (_BACKEND / p)


def run(gold_dir: str, runs_root: str, resume_dir: str | None = None) -> str:
    golds = load_gold_dir(gold_dir)
    if not golds:
        print(f"No gold files in {gold_dir}. Nothing to run.")
        return ""

    # Resume into an existing run dir (skip docs already cached), or start a fresh timestamped run.
    if resume_dir:
        run_dir = Path(resume_dir)
        if not run_dir.exists():
            raise SystemExit(f"--resume dir not found: {run_dir}")
        manifest_path = run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        done = sum(1 for v in manifest.values() if "report" in v)
        print(f"[resume] {run_dir}: {done} docs already cached — skipping those, running the rest.")
    else:
        run_dir = Path(runs_root) / time.strftime("%Y%m%d-%H%M%S")
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = run_dir / "manifest.json"
        manifest = {}

    for gd in golds:
        gid = gd.gold_id
        # Skip docs already completed (have a cached report) — enables --resume; error-only entries retry.
        if gid in manifest and "report" in manifest[gid]:
            continue
        doc_path = _resolve(gd.document)
        out_dir = run_dir / gid
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"[run] {gid}: {doc_path} …", flush=True)
        try:
            result = run_pipeline(document_path=str(doc_path), original_filename=doc_path.name)
        except Exception as exc:  # noqa: BLE001
            manifest[gid] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"  ! pipeline error: {exc}")
            _write(manifest_path, manifest)
            continue

        report_json = Path(result.report_path).with_suffix(".json") if result.report_path else None
        if report_json and not report_json.is_absolute():
            report_json = _BACKEND / report_json
        report = json.loads(report_json.read_text(encoding="utf-8")) if report_json and report_json.exists() else {}
        sidecar = build_sidecar(result.final_state.get("clauses", {}))

        (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (out_dir / "sidecar.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
        manifest[gid] = {
            "gold": gd.source_path,
            "document_id": result.final_state.get("document_id"),
            "report": str((out_dir / "report.json").relative_to(run_dir)),
            "sidecar": str((out_dir / "sidecar.json").relative_to(run_dir)),
            "ingest_error": bool(result.ingest_error or report.get("ingest_error")),
        }
        _write(manifest_path, manifest)
        # ASCII-only marker: a raw U+2713 here crashes the default Windows console (cp1252) mid-run.
        print(f"  [ok] {len(report.get('findings', []))} findings, {len(sidecar)} clauses cached")

    print(f"\nRun cached at {run_dir}\n  score with:  python -m eval.harness.score {run_dir}")
    return str(run_dir)


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the pipeline over the gold corpus (delivery off).")
    ap.add_argument("--gold", default="eval/gold", help="gold label dir (default: eval/gold)")
    ap.add_argument("--runs", default="eval/runs", help="runs cache root (default: eval/runs)")
    ap.add_argument("--resume", default=None,
                    help="resume into an existing run dir (e.g. eval/runs/<ts>): skip already-cached docs")
    args = ap.parse_args()
    run(args.gold, args.runs, resume_dir=args.resume)


if __name__ == "__main__":
    main()
