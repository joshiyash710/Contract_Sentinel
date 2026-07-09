"""
Delivery smoke test: exercise the real Drive + Gmail MCP path against an existing
report on disk, without running the 7-node pipeline.

Picks the most recent *.md report in REPORT_OUTPUT_DIR, builds a minimal state
dict, and calls deliver_report_sync with a real recipient. Prints the resulting
mcp_delivery_status. Requires google_token.json (run scripts/oauth_bootstrap.py first).

Run from backend/ with the venv's python on PATH so the spawned MCP server
subprocesses (`python -m app.delivery.mcp_servers.*`) resolve the venv interpreter:

    scripts/delivery_smoke.py [recipient@example.com]
"""

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import config as _config  # noqa: E402
from app.delivery import deliver_report_sync  # noqa: E402


def main() -> int:
    recipient = sys.argv[1] if len(sys.argv) > 1 else _config.MCP_DELIVERY_RECIPIENT
    if not recipient:
        print("ERROR: no recipient — pass one as an argument or set "
              "CONTRACTSENTINEL_DELIVERY_RECIPIENT")
        return 1

    reports_dir = BACKEND_DIR / _config.REPORT_OUTPUT_DIR
    md_reports = sorted(reports_dir.glob("*.md"), key=lambda p: p.stat().st_mtime)
    if not md_reports:
        print(f"ERROR: no *.md reports found in {reports_dir}")
        return 1

    report_path = md_reports[-1]
    document_id = report_path.stem
    state = {
        "report_path": str(report_path),
        "document_id": document_id,
        "original_filename": f"{document_id}.pdf",
    }

    print(f"Report    : {report_path}")
    print(f"Recipient : {recipient}")
    print(f"Drive={_config.MCP_DRIVE_ENABLED} Gmail={_config.MCP_GMAIL_ENABLED} "
          f"formats={_config.MCP_DRIVE_UPLOAD_FORMATS}")
    print("\nDelivering...\n")

    result = deliver_report_sync(state, recipient=recipient)
    status = result.get("mcp_delivery_status", {})
    print(json.dumps(status, indent=2, default=str))

    ok = bool(status) and all(v.get("status") == "success" for v in status.values())
    print("\nSMOKE:", "PASS" if ok else "FAIL")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
