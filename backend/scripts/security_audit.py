"""
Dependency vulnerability audit (Security Tier 2, item 7 - the scan half).

Runs both dependency audits and exits non-zero when a finding at or above a
configurable severity threshold is present:

  * Backend  - ``pip-audit`` over the resolved Python environment (this repo pins
    deps in ``pyproject.toml`` + ``uv.lock``; there is no ``requirements.txt``).
    A ``requirements.txt`` is used automatically if one is present.
  * Frontend - ``npm audit --json`` over ``frontend/package-lock.json``. A full
    audit and a production-only audit (``--omit=dev``) are both run so dev-only
    findings can be distinguished from prod ones.

Both auditors reach their advisory sources over the network
(pip-audit -> PyPI/OSV, npm audit -> the npm registry), so this script needs
network access to produce real findings.

Exit codes:
    0  no findings at or above the threshold (audits ran clean)
    1  usage / environment error (a required tool is missing, no network, etc.)
    2  vulnerabilities found at or above the threshold

Run from the repo root or from ``backend/``::

    python backend/scripts/security_audit.py
    python backend/scripts/security_audit.py --severity high
    python backend/scripts/security_audit.py --skip-frontend

The ``--severity`` threshold (default ``low``) applies to the frontend npm
audit, whose findings are severity-graded. pip-audit does not grade severity,
so ANY backend finding counts (skip it with ``--skip-backend`` if needed).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"

# npm severities, ascending. A finding "counts" if its severity index is >= the
# threshold's index.
_SEVERITY_ORDER = ["info", "low", "moderate", "high", "critical"]


def _severity_at_or_above(severity: str, threshold: str) -> bool:
    try:
        return _SEVERITY_ORDER.index(severity) >= _SEVERITY_ORDER.index(threshold)
    except ValueError:
        # Unknown severity label -> be conservative and count it.
        return True


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)


# --------------------------------------------------------------------------- #
# Backend: pip-audit
# --------------------------------------------------------------------------- #
def audit_backend() -> tuple[bool, int]:
    """Return (ran_ok, num_findings). ran_ok is False on tool/usage failure."""
    print("\n=== Backend: pip-audit ===", flush=True)

    base_cmd: list[str] | None = None
    if shutil.which("pip-audit") is not None:
        base_cmd = ["pip-audit"]
    else:
        import importlib.util

        if importlib.util.find_spec("pip_audit") is not None:
            base_cmd = [sys.executable, "-m", "pip_audit"]

    if base_cmd is None:
        print(
            "  ! pip-audit is not installed. Install it with:\n"
            "      python -m pip install pip-audit\n"
            "    (a dev-only tool; not added to runtime deps)."
        )
        return (False, 0)

    # Prefer a requirements file if one is present; otherwise audit the resolved
    # environment (which reflects the uv.lock-resolved versions).
    req = BACKEND_DIR / "requirements.txt"
    cmd = list(base_cmd) + ["--format", "json"]
    if req.exists():
        cmd += ["-r", str(req)]

    proc = _run(cmd, cwd=BACKEND_DIR)
    findings = 0
    try:
        data = json.loads(proc.stdout or "{}")
        deps = data.get("dependencies", data if isinstance(data, list) else [])
        for dep in deps:
            if not isinstance(dep, dict):
                continue
            for v in dep.get("vulns", []) or []:
                findings += 1
                fixes = ", ".join(v.get("fix_versions", []) or ["(none)"])
                print(
                    f"  VULN {dep.get('name')}=={dep.get('version')}  "
                    f"{v.get('id')}  fix-> {fixes}"
                )
    except json.JSONDecodeError:
        # pip-audit couldn't run cleanly (e.g. no network). Surface its stderr.
        print("  ! pip-audit did not return JSON; raw output:")
        print("   ", (proc.stderr or proc.stdout or "(no output)").strip()[:2000])
        return (False, 0)

    if findings == 0:
        print("  OK: no known vulnerabilities in backend dependencies.")
    return (True, findings)


# --------------------------------------------------------------------------- #
# Frontend: npm audit
# --------------------------------------------------------------------------- #
def _npm_audit(cwd: Path, prod_only: bool) -> dict | None:
    # Resolve the full path so this works on Windows, where `npm` is `npm.cmd`
    # and cannot be exec'd by name without shell=True (WinError 2 otherwise).
    npm = shutil.which("npm")
    if npm is None:
        print("  ! npm is not on PATH; skipping frontend audit.")
        return None
    cmd = [npm, "audit", "--json"]
    if prod_only:
        cmd.append("--omit=dev")
    proc = _run(cmd, cwd=cwd)
    # npm audit exits non-zero when vulns are found; JSON is still on stdout.
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        print("  ! npm audit did not return JSON; raw output:")
        print("   ", (proc.stderr or proc.stdout or "(no output)").strip()[:2000])
        return None


def _count_npm_findings(report: dict, threshold: str) -> int:
    """Count advisories at/above threshold from an npm-audit v2 (npm>=7) report."""
    count = 0
    for name, node in (report.get("vulnerabilities") or {}).items():
        sev = node.get("severity", "info")
        if _severity_at_or_above(sev, threshold):
            count += 1
            fix = node.get("fixAvailable")
            if isinstance(fix, dict):
                fix_str = f"{fix.get('name')}@{fix.get('version')}"
            elif fix is True:
                fix_str = "available (npm audit fix)"
            else:
                fix_str = "no non-breaking fix"
            print(f"  VULN {name}  severity={sev}  fix-> {fix_str}")
    return count


def audit_frontend(threshold: str) -> tuple[bool, int]:
    print("\n=== Frontend: npm audit ===", flush=True)
    if not (FRONTEND_DIR / "package-lock.json").exists():
        print("  ! no package-lock.json; skipping frontend audit.")
        return (False, 0)

    full = _npm_audit(FRONTEND_DIR, prod_only=False)
    if full is None:
        return (False, 0)

    print(f"  -- full (prod + dev), threshold={threshold} --")
    full_findings = _count_npm_findings(full, threshold)

    prod = _npm_audit(FRONTEND_DIR, prod_only=True)
    prod_findings = 0
    if prod is not None:
        print(f"  -- production only (--omit=dev), threshold={threshold} --")
        prod_findings = _count_npm_findings(prod, threshold)

    if full_findings == 0:
        print("  OK: no frontend vulnerabilities at or above threshold.")
    else:
        print(
            f"  {full_findings} finding(s) total; {prod_findings} in production "
            f"dependencies (rest are dev-only)."
        )
    # Gate on the full audit so dev-tooling CVEs are not silently ignored.
    return (True, full_findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run backend + frontend dependency vulnerability audits."
    )
    parser.add_argument(
        "--severity",
        choices=_SEVERITY_ORDER,
        default="low",
        help="Minimum npm-audit severity that fails the gate (default: low).",
    )
    parser.add_argument("--skip-backend", action="store_true")
    parser.add_argument("--skip-frontend", action="store_true")
    args = parser.parse_args(argv)

    total_findings = 0
    tool_failures = 0

    if not args.skip_backend:
        ran_ok, n = audit_backend()
        total_findings += n
        if not ran_ok:
            tool_failures += 1

    if not args.skip_frontend:
        ran_ok, n = audit_frontend(args.severity)
        total_findings += n
        if not ran_ok:
            tool_failures += 1

    print("\n=== Summary ===")
    print(f"  findings at/above threshold: {total_findings}")
    if tool_failures:
        print(f"  auditors that could not run: {tool_failures}")

    if total_findings > 0:
        print("  RESULT: FAIL (vulnerabilities found)")
        return 2
    if tool_failures:
        # No findings, but at least one auditor could not run -> treat as a
        # usage/environment error so CI does not report a false all-clear.
        print("  RESULT: ERROR (an auditor could not run)")
        return 1
    print("  RESULT: PASS (clean)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
