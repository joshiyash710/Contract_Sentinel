# Feature 033 — Drive Folder + Human-Readable Report Naming — Tasks

Implements `specs/033-drive-folder-report-naming/plan.md` (spec + plan spec-reviewer-APPROVED).
Delivery-layer only: **no `graph/`, no `ContractState`, no Alembic migration, no frontend.**

**Conventions for the implementer (constitution §7, §8):**
- TDD: write the test(s) in each `T*-test` task and **run them, confirm they FAIL** before writing the
  implementation task that follows. Never weaken a test to make it pass — fix the code.
- Run backend tests from `backend/` with: `python -X utf8 -m pytest <path> -q`.
- Do not touch anything outside the file list in plan §8.
- The `drive_server` runs as a **separate subprocess**; it must act on `req.folder_name` /
  `req.folder_id` only — never on `delivery_step` module-level constants (plan §1). The orchestrator
  reads the config and passes values on the request.
- Escape order in `drive_escape` is **backslash first, then single quote** — do not reorder.

---

## Phase A — Config (no test; pure constants)

- **T1** In `app/config.py`, in the MCP delivery block (after ~L384, near the 030 constants), add the
  five named constants from plan §1, verbatim, with the `Optional` import already present:
  ```python
  # ── Feature 033 — Drive folder + human-readable report naming (delivery-layer, reversible) ──
  MCP_DRIVE_FOLDER_NAME: Optional[str] = "ContractSentinel"
  MCP_DRIVE_HUMAN_READABLE_NAMES: bool = True
  MCP_DRIVE_REPORT_NAME_TEMPLATE: str = "{stem} — Risk Report ({disc})"
  MCP_DRIVE_NAME_DISCRIMINATOR_CHARS: int = 6
  MCP_DRIVE_NAME_MAX_STEM_CHARS: int = 120
  ```
  Do NOT remove or edit `MCP_DRIVE_FOLDER_ID`.

---

## Phase B — Naming helper (`report_naming.py`) — TDD

- **T2-test** Create `tests/unit/test_report_naming.py`. Write tests (import from
  `app.delivery.report_naming`), then run and confirm they FAIL (module doesn't exist yet):
  - `drive_escape("O'Brien")` → `"O\\'Brien"`; `drive_escape("a\\b")` → `"a\\\\b"`;
    order test: `drive_escape("a\\'b")` → `"a\\\\\\'b"` (backslash escaped first).
  - `sanitize_stem(...)` — assert **invariants only** (not an exact string, to avoid brittleness):
    given `"a/b\\c"` and `"a\x00b\nc"`, the result contains no `/`, no `\`, and no control chars; and
    with `config.MCP_DRIVE_NAME_MAX_STEM_CHARS` monkeypatched small, `len(result) <=` that cap. T3 must
    implement `sanitize_stem` to exactly these invariants (strip separators + control chars, collapse
    whitespace, cap length) so the test stays a fixed contract.
  - `report_base_name("Acme MSA.pdf", "a3f1c9e2xxxx")` → `"Acme MSA — Risk Report (a3f1c9)"`
    (extension stripped, disc = first 6 of document_id).
  - `report_base_name("", "a3f1c9e2xxxx")` → falls back to full document_id as stem:
    `"a3f1c9e2xxxx — Risk Report (a3f1c9)"` (AC-9).
  - `report_base_name("weird///.pdf", "a3f1c9e2xxxx")` where sanitize empties the stem → falls back to
    document_id stem (AC-9).
  - `drive_file_name("Acme MSA — Risk Report (a3f1c9)", "json")` →
    `"Acme MSA — Risk Report (a3f1c9).json"`.

- **T3-impl** Create `app/delivery/report_naming.py` (plan §2) with `drive_escape`, `sanitize_stem`,
  `report_base_name`, `drive_file_name`. Pure functions, stdlib only (`os.path.splitext`, `re`), read
  caps/template/disc-chars from `app.config`. Make T2 tests pass. Run `test_report_naming.py` green.

---

## Phase C — Foldering server-side (`drive_server` + models + client) — TDD

- **T4-test** In `tests/unit/test_mcp_servers.py`, extend the `_make_drive_service` helper. **Do NOT
  key results by call ordinal** — the number of `files().list` calls differs per branch (folder_name
  path = 2 list calls; explicit-`folder_id` and root paths = 1 list call, the name-match). Instead:
  - The fake `svc.files().list(q=..., ...)` must **inspect the `q` string** and return the folder-list
    result when `q` contains `mimeType='application/vnd.google-apps.folder'`, else return the
    name-match result. (Configure the helper with `folder_list=[...]` and `name_match_list=[...]`.)
  - The fake `svc.files().create(body=..., ...)` must **branch on `body["mimeType"]`**: when it equals
    `application/vnd.google-apps.folder` it is a **folder-create** (return `{"id": <folderId>}`, or raise
    for AC-16); otherwise it is the **file-create** (return the webViewLink result). This one capability
    covers both AC-1 (folder create happens) and AC-16 (folder create raises while file path is fine).
  Then add failing tests:
  - **AC-1** `folder_name="ContractSentinel"`, `folder_id=None`, folder-list empty → asserts a folder
    `create` (body mimeType `application/vnd.google-apps.folder`, name `ContractSentinel`) happened,
    then file `create` called with `parents=[<new folder id>]`.
  - **AC-2** folder-list returns `[{"id":"F1"}]` → no folder `create`; the name-match `q` is scoped
    with `'F1' in parents`, and the file is created with `parents=["F1"]` (or, if a same-name file
    already exists in that folder, `update`d — note `files().update` takes no `parents` kwarg, so the
    load-bearing assertion is the `'F1' in parents` scoping of the name-match `q`, per AC-6a).
  - **AC-3** folder-list returns two ids → assert the folder `list` was called with
    `orderBy="createdTime"` and the **first** (`files[0]`) id is used; no folder create.
  - **AC-4** `folder_id="EXPLICIT"` set → assert the **folder-resolution query** (a `files().list`
    whose `q` contains `mimeType='application/vnd.google-apps.folder'`) was **never** issued, while the
    **name-match** `files().list` (whose `q` contains `'EXPLICIT' in parents`) **was**; and file
    create/update uses `parents=["EXPLICIT"]`. (Assert on the `q` content of
    `svc.files().list.call_args_list`, not on total call count.)
  - **AC-5** `folder_name=None`, `folder_id=None` → name-match `q` has **no** `in parents` term; create
    `parents=[]`.
  - **AC-6** parametrize `token_path` = a per-user path and `None` (central) → resolve/create identical
    (the fake ignores token, but assert both paths reach create with the resolved parent).
  - **AC-6a** on the found/created/explicit paths, assert the name-match `q` string contains
    `'<resolvedId>' in parents`.
  - **AC-12** `file_name="O'Brien (a3f1c9).pdf"` and `folder_name="Con'tract"` → assert the exact `q`
    strings passed to `files().list` contain `O\\'Brien` and `Con\\'tract` (escaped), and no exception
    is raised.
  - **AC-16** two sub-cases: (i) the folder-resolution `files().list` raises
    `googleapiclient.errors.HttpError`; (ii) the **folder-create** raises `HttpError` (via the
    `body["mimeType"]==…folder` branch of the fake) while file-create would otherwise succeed. In both,
    `_handle_upload` returns `ToolOutcome(ok=False)` and does **not** raise.
  Run and confirm all FAIL.

- **T5-impl** `app/delivery/models.py`: add `folder_name: Optional[str] = None` to `DriveUploadRequest`.

- **T6-impl** `app/delivery/mcp_servers/drive_server.py` (plan §3):
  1. `from app.delivery.report_naming import drive_escape`.
  2. Add a `_resolve_folder_id(svc, req)` step producing `resolved_folder_id`:
     - `req.folder_id` truthy → return it (no query).
     - elif `req.folder_name` → list folders with
       `q=f"mimeType='application/vnd.google-apps.folder' and name='{drive_escape(req.folder_name)}' and trashed=false"`,
       `fields="files(id)"`, `orderBy="createdTime"`; return `files[0]["id"]` if any else create a folder
       (`body={"name": req.folder_name, "mimeType": "application/vnd.google-apps.folder"}`, `fields="id"`)
       and return its id.
     - else → return `None`.
  3. Build name-match: `folder_query = f" and '{resolved_folder_id}' in parents" if resolved_folder_id else ""`;
     `q = f"name='{drive_escape(req.file_name)}'{folder_query} and trashed=false"`.
  4. Create path: `parents=[resolved_folder_id] if resolved_folder_id else []`.
  5. Keep everything inside the existing `try/except HttpError/except Exception` so folder errors →
     `ToolOutcome(ok=False)`.
  6. Add `folder_name` to the `upload_file` tool `inputSchema` (`:100-111`):
     `"folder_name": {"type": ["string", "null"]}`.
  Make T4 tests pass. Run `test_mcp_servers.py` green.

- **T7-impl** `app/delivery/mcp_clients/drive_client.py`: add `folder_name: Optional[str] = None` kwarg to
  `upload_report_to_drive`, set it on `DriveUploadRequest`. Update the public-API docstring in
  `app/delivery/mcp_clients/__init__.py` to include `folder_name`.

---

## Phase D — Human-readable naming in the orchestrator (`delivery_step`) — TDD

- **T8-test** In `tests/unit/test_delivery_step.py`, add failing tests (stub/patch
  `app.delivery.delivery_step.upload_report_to_drive` to capture the `file_name` and `folder_name` it
  receives; monkeypatch the module-level `MCP_DRIVE_*` names as the existing tests do):
  - **AC-7** `original_filename="Acme MSA.pdf"`, `document_id="a3f1c9e2…"`, human-readable ON →
    Drive receives `file_name="Acme MSA — Risk Report (a3f1c9).pdf"` for the pdf and
    `"…(a3f1c9).json"` for json; and `folder_name="ContractSentinel"` is passed.
  - **AC-8** the local report file paths (`report_path` + siblings) are unchanged on disk (assert the
    stubbed uploader was given the real local `file_path` but a different `file_name`).
  - **AC-10** `MCP_DRIVE_HUMAN_READABLE_NAMES=False` → Drive `file_name` == local `path.name`
    (`{document_id}.pdf`).
  - **AC-11** two deliveries with same `original_filename="NDA.pdf"` but different `document_id`s →
    two **distinct** `file_name`s (different `{disc}`).
  - **AC-14** Gmail attachment name equals the human-readable name (patch/inspect
    `send_report_via_gmail` args), and gmail still records SUCCESS.
  - **AC-15** regression: with PDF render forced to fail, delivery still falls back to md and still
    sends email (existing behavior preserved).
  - **AC-17** force the Drive upload to fail via a folder-resolution error path (uploader returns
    `DeliveryResult(ok=False)`); assert no per-user/central plaintext temp token file remains on disk
    after `deliver_report` returns (the `finally` blocks ran).
  Run and confirm FAIL.

- **T9-impl** `app/delivery/delivery_step.py` (plan §4):
  1. Re-expose the 5 new config constants at module level (mirror `:38-49`). **These are read ONLY by
     the orchestrator and passed on the request** (`folder_name=MCP_DRIVE_FOLDER_NAME`); never import or
     rely on them inside `drive_server` (it runs in a separate subprocess — see preamble).
  2. In `deliver_report`, after `original_filename` is read (~`:203`), compute
     `base_name = report_base_name(original_filename, document_id) if MCP_DRIVE_HUMAN_READABLE_NAMES else None`.
  3. Pass `base_name` into `_deliver_drive`; for each format, the `file_name` argument becomes
     `drive_file_name(base_name, ext)` when `base_name` else `path.name` (here `ext` is the loop's
     current format key `"pdf"`/`"json"`/`"md"`). Also pass `folder_name=MCP_DRIVE_FOLDER_NAME` (and keep
     `folder_id=MCP_DRIVE_FOLDER_ID`) to `upload_report_to_drive`.
  4. Gmail attachment name (`:277`, currently `attach_path.name`): when `base_name`, derive the
     extension from the chosen `attach_path` — `attach_ext = attach_path.suffix.lstrip(".")` (yields
     `"pdf"` or `"md"`) — and pass `drive_file_name(base_name, attach_ext)` as the `attachment_name`
     (the 5th positional arg to `send_report_via_gmail`) instead of `attach_path.name`. Keep
     `attach_path` (the bytes source) unchanged.
  Make T8 tests pass. Run `test_delivery_step.py` green.

---

## Phase E — Full regression + smoke

- **T10** Run the whole backend suite: `python -X utf8 -m pytest -q` from `backend/`. All green
  (existing 030/031/032 delivery tests must still pass — AC-15).
- **T11** (optional live smoke, if OAuth available) Run `scripts/delivery_smoke.py <email>` and confirm
  in Drive that a `ContractSentinel` folder exists containing a report named
  `… — Risk Report (<6-char id>).pdf` (+ `.json`), and the delivery email's attachment carries the same
  name. If OAuth is unavailable, note it and rely on T10.

---

## AC-coverage map

| AC | Task(s) |
|----|---------|
| AC-1, AC-2, AC-3 | T4 / T6 |
| AC-4 | T4 / T6 |
| AC-5 | T4 / T6 |
| AC-6, AC-6a | T4 / T6 |
| AC-7 | T2/T3, T8/T9 |
| AC-8 | T8 / T9 |
| AC-9 | T2 / T3 |
| AC-10 | T8 / T9 |
| AC-11 | T8 / T9 |
| AC-12 | T2/T3 (escape), T4/T6 (`q` usage) |
| AC-13 | T2 / T3 |
| AC-14 | T8 / T9 |
| AC-15 | T8, T10 |
| AC-16 | T4 / T6 |
| AC-17 | T8 / T9 |

## Files touched (must match plan §8)

`app/config.py`, `app/delivery/report_naming.py` (new), `app/delivery/models.py`,
`app/delivery/mcp_servers/drive_server.py`, `app/delivery/mcp_clients/drive_client.py`,
`app/delivery/mcp_clients/__init__.py`, `app/delivery/delivery_step.py`,
`tests/unit/test_report_naming.py` (new), `tests/unit/test_mcp_servers.py`,
`tests/unit/test_delivery_step.py`.
