"""
Human-readable Drive/email report naming helpers (feature 033).

Pure, side-effect-free functions shared by the delivery orchestrator (Drive file
name + Gmail attachment name) and the Drive MCP server (`q`-query escaping). No
I/O; config-driven via app.config so the template/caps stay §3-tunable.

Decisions (see specs/033-drive-folder-report-naming/spec.md):
  1. Names carry a short document_id discriminator so distinct jobs never collide.
  2. Template "{stem} — Risk Report ({disc})"; JSON sibling renamed to match.
  5. Escape single quotes/backslashes for the Drive v3 `q` grammar; strip path
     separators + control chars from the stored name; cap the stem length.
"""

import os
import re

import app.config as _config

# Control chars (incl. newline/tab) and the two path separators are stripped from
# any value used as a Drive *file name* (AC-13). This is NOT the `q`-query escape
# (that is drive_escape, a different sink).
_STRIP_RE = re.compile(r"[\x00-\x1f\x7f/\\]")
_WS_RE = re.compile(r"\s+")


def drive_escape(value: str) -> str:
    """Escape a value for inclusion inside a single-quoted Drive v3 `q` term (AC-12).

    Order matters: escape backslash first, then the single quote — otherwise the
    backslash inserted in front of a quote would itself be doubled.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


def sanitize_stem(name: str) -> str:
    """Strip path separators + control chars from a Drive file-name stem, collapse
    whitespace, and cap the length (AC-13). May return '' — callers fall back to
    the document_id (AC-9)."""
    cleaned = _STRIP_RE.sub("", name)
    cleaned = _WS_RE.sub(" ", cleaned).strip()
    cap = _config.MCP_DRIVE_NAME_MAX_STEM_CHARS
    if cap and len(cleaned) > cap:
        cleaned = cleaned[:cap].rstrip()
    return cleaned


def report_base_name(original_filename: str, document_id: str) -> str:
    """Build the human-readable base name (no extension) from the template
    (Decisions 1/2). Falls back to the full document_id as the stem when
    original_filename is blank or sanitizes to empty (AC-9)."""
    stem = sanitize_stem(os.path.splitext(original_filename or "")[0])
    if not stem:
        stem = document_id
    disc = document_id[: _config.MCP_DRIVE_NAME_DISCRIMINATOR_CHARS]
    return _config.MCP_DRIVE_REPORT_NAME_TEMPLATE.format(stem=stem, disc=disc)


def drive_file_name(base_name: str, ext: str) -> str:
    """Append the format extension (without a leading dot) to the base name."""
    return f"{base_name}.{ext.lstrip('.')}"
