"""
CLI entry point for the ContractSentinel pipeline runner.

Usage:
    python -m app.runner <contract_file> [--recipient EMAIL] [--checkpoint]

Shares the exact run_pipeline core with the API worker — no forked logic (spec D2).
Progress is printed to stderr; the final report path is printed to stdout.

--checkpoint enables the SQLite checkpointer for resume testing (feature 012).
"""

import argparse
import sys
from uuid import uuid4

from app.runner.core import run_pipeline, NodeProgress


def _on_progress(p: NodeProgress) -> None:
    print(f"[{p.index}/{p.total}] {p.node}", file=sys.stderr)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the ContractSentinel pipeline.")
    parser.add_argument("file", help="Path to the contract file (.pdf or .docx)")
    parser.add_argument(
        "--recipient", default=None, help="Email recipient for MCP delivery"
    )
    parser.add_argument(
        "--checkpoint",
        action="store_true",
        help="Enable the SQLite checkpointer for resume testing (feature 012)",
    )
    args = parser.parse_args(argv)

    saver = None
    thread_id = None
    if args.checkpoint:
        import app.config as _cfg
        from app.runner.persistence import build_saver

        saver = build_saver(_cfg.CHECKPOINTER_DB_PATH)
        thread_id = str(uuid4())

    try:
        result = run_pipeline(
            args.file,
            recipient=args.recipient,
            on_progress=_on_progress,
            checkpointer=saver,
            thread_id=thread_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if result.ingest_error:
        msg = result.ingest_error.get("message", str(result.ingest_error))
        print(f"Ingest error: {msg}", file=sys.stderr)
        return 2

    print(f"Report: {result.report_path}")
    if result.mcp_delivery_status:
        print(f"Delivery: {result.mcp_delivery_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
