# Feature 033 — Drive Folder + Human-Readable Report Naming — Technical Plan

**Branch:** `feature/033-drive-folder-report-naming` — git workflow per constitution §11 (this line is
the only workflow statement here; the rules live in §11, not restated).

Implements the spec-reviewer-APPROVED `specs/033-drive-folder-report-naming/spec.md`. This is a
**delivery-layer-only** feature: **no LangGraph node/edge change, no `ContractState` field, no
migration.** Authorized under the existing 010/030/031 delivery amendments (constitution §2) — it
refines Drive output only. All new tunables are named `app/config.py` constants (§3). Decisions 1–5
are resolved in the spec; this plan does not re-open them.

TDD per constitution §7: for each work-stream the tests below are written and confirmed **failing**
first, then the implementation makes them pass; tests are never weakened to force a pass. Run backend
tests with `python -X utf8 -m pytest` from `backend/`.

---

## 0. Grounding (verified against current code)

- **Single Drive tool seam** is `drive_server._handle_upload(req: DriveUploadRequest)`
  (`app/delivery/mcp_servers/drive_server.py:33-85`). It already:
  builds the query `q = f"name='{req.file_name}'{folder_query} and trashed=false"` where
  `folder_query` is `" and '{req.folder_id}' in parents"` **only when `req.folder_id` is truthy**
  (`:45-46`), lists (`:48-51`), then `update`s if a match exists else `create`s with
  `parents=[req.folder_id] if req.folder_id else []` (`:57-74`). → The find-or-create folder logic and
  the `q`-escaping both belong **here**, because this is the only place with an authenticated `svc`
  and the correct (per-user vs central) Drive already selected by `token_path` (`:37`).
- **`req.file_name` is interpolated into `q` unescaped today** (`:45`) — a live latent bug the spec's
  AC-12 closes.
- **Transport model** `DriveUploadRequest` (`app/delivery/models.py:14-20`) has
  `file_path, file_name, mime_type, folder_id, token_path`. It needs a new optional `folder_name`.
- **Client passthrough**: `upload_report_to_drive(...)` (`app/delivery/mcp_clients/drive_client.py:15-45`)
  builds the `DriveUploadRequest` and calls `call_tool_with_retry`. It needs a new `folder_name` kwarg;
  its docstring in `mcp_clients/__init__.py:5` is updated.
- **Orchestrator** `_deliver_drive(...)` (`app/delivery/delivery_step.py:108-164`) currently passes
  `path.name` as `file_name` and `MCP_DRIVE_FOLDER_ID` as `folder_id` (`:137-145`). This is where the
  human-readable name is computed (from `state["original_filename"]`/`document_id`, already read at
  `delivery_step.py:203`) and where `folder_name` is threaded in.
- **Gmail attachment name** is `attach_path.name` (`delivery_step.py:269,279`). Decision 4 → reuse the
  same name helper for the attachment.
- **Token-cleanup `finally` blocks** the spec's AC-17 depends on are real:
  per-user unlink at `delivery_step.py:242-246`, central `_central_is_temp` unlink at `:284-290`.
  No change needed — AC-17 is a *non-regression assertion* that the new failure point (inside the
  subprocess) doesn't bypass them.
- **Test harness**: `tests/unit/test_mcp_servers.py` drives `_handle_upload` directly with a fake `svc`
  via `_make_drive_service(list_files=..., create_result=..., update_result=...)` and patches
  `load_credentials`/`build_drive_service`/`MediaFileUpload` (`:39-113`). The fake currently returns one
  canned `list` result; folder find-or-create makes **two** `files().list` calls (folder query, then
  name-match), so `_make_drive_service` is extended to return a **sequence** of list results (and to
  distinguish a folder `create` from a file `create`). `tests/unit/test_delivery_step.py` drives the
  orchestrator with a stubbed `upload_report_to_drive` capturing the `file_name`/`folder_name` it
  receives.
- **No migration**: current Alembic head is unchanged; this feature adds none.

---

## 1. Config (constitution §3 — named constants in `app/config.py`, near the existing MCP block ~`:357-384`)

```python
# ── Feature 033 — Drive folder + human-readable report naming (delivery-layer, reversible) ──
MCP_DRIVE_FOLDER_NAME: Optional[str] = "ContractSentinel"   # find-or-create target; None/"" → root (pre-033)
MCP_DRIVE_HUMAN_READABLE_NAMES: bool = True                 # False → pre-033 document_id names
MCP_DRIVE_REPORT_NAME_TEMPLATE: str = "{stem} — Risk Report ({disc})"
MCP_DRIVE_NAME_DISCRIMINATOR_CHARS: int = 6                 # leading document_id chars for {disc}
MCP_DRIVE_NAME_MAX_STEM_CHARS: int = 120                    # cap on {stem}
```

`MCP_DRIVE_FOLDER_ID` (existing, `config.py:368`) is retained and takes precedence (Decision 3 / AC-4).
Each constant is re-exposed at module level in `delivery_step.py` (mirroring the existing
`MCP_DRIVE_FOLDER_ID = _config.MCP_DRIVE_FOLDER_ID` pattern at `delivery_step.py:38-49`) so tests can
monkeypatch without touching `_config`. **These re-exposed names live in the parent process only.** The
`drive_server` subprocess must NOT rely on them: the folder name is **authoritative via
`req.folder_name`** (threaded through `DriveUploadRequest`, §3.3) — the orchestrator reads
`MCP_DRIVE_FOLDER_NAME`/`MCP_DRIVE_FOLDER_ID` and passes them on the request, and the server acts only
on `req.folder_name`/`req.folder_id`. This is what keeps the orchestrator's monkeypatched values honored
without depending on subprocess module-level visibility.

Grounding note (spec review suggestion 2): `document_id[:N]` is safe even if the id is shorter than `N`
(Python slice truncates); the system-generated id is always longer, so `{disc}` is well-defined.

---

## 2. New helper module — `app/delivery/report_naming.py`

A tiny, pure, side-effect-free module so both the orchestrator (Drive file name + Gmail attachment
name) and tests share one implementation (Decision 2/4/5). Pure functions, no I/O:

```python
def drive_escape(value: str) -> str:
    """Escape a value for inclusion inside a single-quoted Drive v3 `q` term.
    Order matters: backslash first, then single quote (AC-12)."""
    return value.replace("\\", "\\\\").replace("'", "\\'")

def sanitize_stem(name: str) -> str:
    """Strip path separators + control chars from a Drive file-name stem, collapse
    whitespace, cap length (AC-13). May return '' → caller falls back to document_id."""

def report_base_name(original_filename: str, document_id: str) -> str:
    """Build the human-readable base name (no extension) from the template (Decision 1/2):
    stem = sanitize_stem(splitext(original_filename)[0]); if empty → document_id.
    disc = document_id[:MCP_DRIVE_NAME_DISCRIMINATOR_CHARS].
    Returns MCP_DRIVE_REPORT_NAME_TEMPLATE.format(stem=stem, disc=disc)."""

def drive_file_name(base_name: str, ext: str) -> str:
    """f\"{base_name}.{ext}\" (ext without dot)."""
```

- `drive_escape` is imported and used **inside `drive_server`** (the only place that builds `q`), for
  both the file name and the folder name (AC-12). It is duplicated there only if a cross-process import
  is undesirable — but `report_naming` is import-safe (pure stdlib), so `drive_server` imports it
  directly.
- `report_base_name`/`drive_file_name`/`sanitize_stem` are used in the **orchestrator**
  (`delivery_step.py`), which computes the name once and passes it as `file_name` for each format and as
  the Gmail attachment name.

---

## 3. Work-stream A — Foldering (server-side find-or-create + resolved-folder scoping)

Files: `app/delivery/mcp_servers/drive_server.py`, `app/delivery/models.py`,
`app/delivery/mcp_clients/drive_client.py`, `app/delivery/mcp_clients/__init__.py` (docstring),
`app/delivery/mcp_servers/drive_server.py` tool schema (`:100-111`, add `folder_name`).

1. `DriveUploadRequest` gains `folder_name: Optional[str] = None`.
2. `drive_client.upload_report_to_drive` gains `folder_name: Optional[str] = None` kwarg, set on the
   request; `__init__.py` public-API docstring updated.
3. In `_handle_upload`, replace the folder handling with a **resolve step** producing a single
   `resolved_folder_id`:
   - If `req.folder_id` (explicit `MCP_DRIVE_FOLDER_ID`) → `resolved_folder_id = req.folder_id`
     (no folder query; AC-4).
   - elif `req.folder_name` → find-or-create:
     `q_folder = f"mimeType='application/vnd.google-apps.folder' and name='{drive_escape(req.folder_name)}' and trashed=false"`,
     `svc.files().list(q=q_folder, fields="files(id)", orderBy="createdTime").execute()`; reuse
     `files[0]["id"]` (oldest, AC-3) else `svc.files().create(body={"name": req.folder_name,
     "mimeType": "application/vnd.google-apps.folder"}, fields="id").execute()["id"]` (AC-1/AC-2).
   - else → `resolved_folder_id = None` (root; AC-5).
4. Build the name-match query **scoped to `resolved_folder_id`** (AC-6a) and **escaped** (AC-12):
   `folder_query = f" and '{resolved_folder_id}' in parents" if resolved_folder_id else ""`;
   `q = f"name='{drive_escape(req.file_name)}'{folder_query} and trashed=false"`.
5. Create path uses `parents=[resolved_folder_id] if resolved_folder_id else []`.
6. All exceptions stay inside the existing `try/except HttpError/except Exception` (`:78-85`) → folder
   failures already map to `ToolOutcome(ok=False)` (AC-16); no new raise escapes.

## 4. Work-stream B — Human-readable naming (orchestrator + Gmail attachment)

Files: `app/delivery/delivery_step.py`, new `app/delivery/report_naming.py`.

1. In `deliver_report`, compute once (after `original_filename` is read, ~`:203`):
   `base = report_base_name(original_filename, document_id)` when
   `MCP_DRIVE_HUMAN_READABLE_NAMES` else `None`.
2. `_deliver_drive` gains a `base_name: Optional[str]` param (or reads the re-exposed flag). For each
   uploaded format, the `file_name` passed to `upload_report_to_drive` becomes
   `drive_file_name(base, ext)` when `base` else `path.name` (AC-7/AC-10). Local `path`/`path.name`
   on disk are untouched (AC-8). `folder_name=MCP_DRIVE_FOLDER_NAME` and the existing
   `folder_id=MCP_DRIVE_FOLDER_ID` are both passed through (server decides precedence).
3. Gmail attachment name (`delivery_step.py:269/279`): when `base` set, use
   `drive_file_name(base, attach_ext)` instead of `attach_path.name` (Decision 4 / AC-14); the local
   `attach_path` used to read bytes is unchanged.
4. Fallback (AC-9): `report_base_name` already returns a `document_id`-based stem when
   `original_filename` is blank/sanitizes empty.

## 5. Non-regression (Work-stream C — assertions, mostly no code)

- AC-15: 030/031/032 behaviors unchanged — the PDF fail-safe→md, per-user vs central token routing,
  not-connected→skip, and central-token temp cleanup are all untouched; covered by keeping existing
  tests green plus targeted asserts.
- AC-17: add a test that a folder-resolution `HttpError` still leaves no per-user/central temp token on
  disk (the `finally` blocks run) — pure assertion, no code change.

---

## 6. Test plan (TDD — write failing first)

Server unit tests (`tests/unit/test_mcp_servers.py`; extend `_make_drive_service` to accept a
**list of** list-results and to tag folder-create vs file-create):
- AC-1 folder absent → folder `create` then file `create` with `parents=[newFolderId]`.
- AC-2 folder present → no folder create; file uploaded with `parents=[existingId]`.
- AC-3 two folders → `orderBy=createdTime`, oldest id reused, no create.
- AC-4 explicit `folder_id` → **no** folder `list` call; name-match `q` and create `parents` both use it.
- AC-5 no name & no id → `parents=[]`, name-match `q` has no `in parents` term.
- AC-6 per-user vs central token both resolve/create (parametrize `token_path`).
- AC-6a name-match `q` contains `'<resolvedId>' in parents` on every resolved path.
- AC-12 `file_name`/`folder_name` with `'` and `\` → exact escaped `q` string asserted; no `HttpError`.
- AC-16 folder `list`/`create` raising `HttpError` → `ToolOutcome(ok=False)`, no raise.

Naming unit tests (new `tests/unit/test_report_naming.py`):
- AC-7 `Acme MSA.pdf` + id `a3f1c9…` → `Acme MSA — Risk Report (a3f1c9).pdf` / `.json`.
- AC-9 blank/empty-after-sanitize → falls back to `document_id` stem.
- AC-13 `/`,`\`, control chars stripped; stem capped at `MCP_DRIVE_NAME_MAX_STEM_CHARS`.
- `drive_escape` order (`\`→`\\` then `'`→`\'`).

Orchestrator unit tests (`tests/unit/test_delivery_step.py`; stub `upload_report_to_drive`):
- AC-7/AC-8 Drive receives human-readable `file_name`; local report paths unchanged.
- AC-10 flag False → `path.name` names.
- AC-14 Gmail attachment name is the human-readable name; email still sends.
- AC-11 two different `document_id`s, same `original_filename` → two distinct `file_name`s.
- AC-15 regression asserts (PDF fail-safe, not-connected skip) still hold.
- AC-17 folder-failure → no temp token left on disk.

Full suite (`python -X utf8 -m pytest` from `backend/`) stays green.

---

## 7. AC-coverage map

| AC | Where satisfied | Test |
|----|-----------------|------|
| AC-1..AC-3, AC-6a | `drive_server` resolve step (§3.3-3.4) | test_mcp_servers |
| AC-4 | `drive_server` explicit-id branch (§3.3) | test_mcp_servers |
| AC-5 | `drive_server` root branch (§3.3-3.5) | test_mcp_servers |
| AC-6 | `drive_server` token_path parametrized | test_mcp_servers |
| AC-7,9,13 | `report_naming` (§2) | test_report_naming |
| AC-8,10,14 | orchestrator (§4) | test_delivery_step |
| AC-11 | orchestrator name = base incl. `{disc}` | test_delivery_step |
| AC-12 | `drive_escape` in `drive_server` (§3.4) | test_mcp_servers + test_report_naming |
| AC-15 | unchanged 030/031/032 paths | existing + new asserts |
| AC-16 | existing `try/except` (§3.6) | test_mcp_servers |
| AC-17 | unchanged `finally` blocks (§5) | test_delivery_step |

## 8. Files touched (all under `backend/app/delivery/` — no `graph/`, no migration, no frontend)

- `app/config.py` — 5 new constants (§1).
- `app/delivery/report_naming.py` — **new** pure helper module (§2).
- `app/delivery/models.py` — `DriveUploadRequest.folder_name`.
- `app/delivery/mcp_servers/drive_server.py` — folder resolve + escaped/scoped `q` + tool schema.
- `app/delivery/mcp_clients/drive_client.py` + `__init__.py` — `folder_name` passthrough + docstring.
- `app/delivery/delivery_step.py` — compute base name; thread `folder_name`/`base_name`; Gmail attach name.
- Tests: `tests/unit/test_mcp_servers.py`, new `tests/unit/test_report_naming.py`,
  `tests/unit/test_delivery_step.py`.

## 9. Out of scope (per spec) / rollback

Everything in spec §"Out of scope". Full rollback is config-only: `MCP_DRIVE_HUMAN_READABLE_NAMES=False`
restores pre-033 names and `MCP_DRIVE_FOLDER_NAME=None` restores root upload — no code path is removed,
only guarded.
