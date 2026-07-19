#!/usr/bin/env python3
"""PostToolUse hook: remind the model to run the spec-reviewer gate.

Fires after a Write/Edit tool call. If the file that was written or edited is a
ContractSentinel spec-driven artifact (specs/**/spec.md | plan.md | tasks.md), it injects a
reminder that the `spec-reviewer` subagent must review and APPROVE the artifact before the
workflow advances to the next stage (see CLAUDE.md "Artifact Review Gate").

The hook only REMINDS — a shell hook cannot spawn a subagent. The review itself and honoring its
verdict are the model's responsibility.

Reads the PostToolUse event JSON from stdin; emits nothing (exit 0) for unrelated files, or a
PostToolUse additionalContext reminder for artifacts.
"""
import json
import re
import sys

# Matches .../specs/<anything>/spec.md | plan.md | tasks.md  (forward or back slashes)
_ARTIFACT_RE = re.compile(r"[\\/]specs[\\/][^\\/]+[\\/](spec|plan|tasks)\.md$", re.IGNORECASE)


def _extract_path(event: dict) -> str:
    tool_input = event.get("tool_input") or {}
    # Write and Edit both carry the target as file_path.
    return tool_input.get("file_path") or tool_input.get("path") or ""


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # nothing parseable → stay silent

    path = _extract_path(event)
    match = _ARTIFACT_RE.search(path.replace("\\", "/") if path else "")
    if not match:
        return 0

    stage = match.group(1)  # spec | plan | tasks
    reminder = (
        f"[Artifact Review Gate] A {stage}.md artifact was just written/edited "
        f"({path}). Per CLAUDE.md, before advancing to the next stage you MUST invoke the "
        f"`spec-reviewer` subagent (Agent tool) on this artifact and only proceed once it returns "
        f"VERDICT: APPROVED. If it returns CHANGES REQUESTED, apply the changes, then re-invoke it."
    )
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": reminder,
        }
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
