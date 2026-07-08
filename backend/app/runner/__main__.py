"""
CLI entry point for the ContractSentinel pipeline runner.

Usage:
    python -m app.runner <contract_file> [--recipient EMAIL]

Shares the exact run_pipeline core with the API worker — no forked logic (spec D2).
Progress is printed to stderr; the final report path is printed to stdout.
"""

import argparse
import sys

from app.runner.core import run_pipeline, NodeProgress


def _on_progress(p: NodeProgress) -> None:
    print(f"[{p.index}/{p.total}] {p.node}", file=sys.stderr)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the ContractSentinel pipeline.")
    parser.add_argument("file", help="Path to the contract file (.pdf or .docx)")
    parser.add_argument(
        "--recipient", default=None, help="Email recipient for MCP delivery"
    )
    args = parser.parse_args(argv)

    try:
        result = run_pipeline(
            args.file, recipient=args.recipient, on_progress=_on_progress
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
