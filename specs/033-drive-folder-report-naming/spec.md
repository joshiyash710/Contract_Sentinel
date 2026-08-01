# Feature 033 — Drive Folder + Human-Readable Report Naming

## Problem statement

Report delivery (feature 010, extended by 030's PDF/HTML and 031's per-user Drive)
currently writes report files to the **root** of the target Google Drive with
**machine-generated file names**:

- `MCP_DRIVE_FOLDER_ID` defaults to `None`, so `_deliver_drive` uploads to the
  account's Drive root (`app/delivery/delivery_step.py`, `app/config.py:368`).
- The uploaded file name is `path.name` of the local report file, which is
  `{document_id}.pdf` / `{document_id}.json` (`REPORT_MD_FILENAME_TEMPLATE`
  et al., `app/config.py:344`). `document_id` is an opaque id, so a user opening
  their Drive sees files like `a3f1c9e2-….pdf` scattered in their root.

This is a **delivery-layer** feature only. It does **not** touch the LangGraph
StateGraph, the 7 fixed nodes, the 2 conditional edges, `ContractState`, or any
migration. It sits entirely in the post-terminal MCP delivery step (constitution
§2 fixed architecture; delivery is "NOT a graph node", per `delivery_step.py`
module docstring). It refines feature 010/030/031 output for humans:

1. **Foldering** — reports are placed inside a single, app-owned **"ContractSentinel"**
   folder in the target Drive (found-or-created on demand), instead of the root.
2. **Human-readable names** — each uploaded report is named after the original
   contract (e.g. `Acme MSA — Risk Report.pdf`) instead of the raw `document_id`.

Both apply to **per-user Drive** (031, when a user has connected Google) **and**
the **central Drive** (pre-031 / `PER_USER_DRIVE_ENABLED=False`) code paths,
since both flow through the same `_deliver_drive` → `upload_report_to_drive` →
`drive_server._handle_upload` chain.

## Inputs and outputs

### Inputs (all already present — no new state fields)

This feature reads only fields that `ContractState`
(`specs/001-contract-state-schema.md`) **already defines**; it introduces **no new
field and changes no existing field**. Consumed at delivery time (via the `state`
dict passed to `deliver_report`):

- `original_filename: str` — the uploaded document's original filename (added by
  IngestAgent; 001 §3). Basis for the human-readable report name.
- `document_id: str` — opaque id (added by IngestAgent; 001 §3). Used as the
  **fallback** name source when `original_filename` is missing/blank, and as the
  uniqueness discriminator (see Decision 1).
- `report_path: Optional[str]` — path to the on-disk Markdown report (added by
  ReportAgent; 001 §3). The local `.pdf`/`.json`/`.md` files are derived from it
  as today. **Local file paths on disk are unchanged** — only the *name sent to
  Drive* (the `file_name` argument) and the *Gmail attachment name* change.

### New configuration (constitution §3 — named constants, no inline literals)

Added to `app/config.py`, all reversible:

- `MCP_DRIVE_FOLDER_NAME: Optional[str] = "ContractSentinel"` — name of the
  folder to find-or-create in the target Drive. `None` or `""` disables
  foldering (upload to root, pre-033 behavior).
- `MCP_DRIVE_HUMAN_READABLE_NAMES: bool = True` — master toggle for the
  human-readable naming. `False` restores the pre-033 `document_id`-based names.
- `MCP_DRIVE_REPORT_NAME_TEMPLATE: str = "{stem} — Risk Report ({disc})"` — base
  name template (extension appended per format). `{stem}` = sanitized
  `original_filename` with its extension stripped; `{disc}` = the Decision-1
  uniqueness discriminator.
- `MCP_DRIVE_NAME_DISCRIMINATOR_CHARS: int = 6` — number of leading `document_id`
  characters used for `{disc}` (Decision 1).
- `MCP_DRIVE_NAME_MAX_STEM_CHARS: int = 120` — cap on `{stem}` length to avoid
  pathological Drive names (Edge case: very long filename).

`MCP_DRIVE_FOLDER_ID` (existing) is retained and takes **precedence**: if an
explicit folder id is configured, it is used verbatim and no find-or-create is
performed (Decision 3, AC-4).

### Outputs

**Unchanged.** `deliver_report` still returns only
`{"mcp_delivery_status": {service: {status, error_message, delivered_at}}}`
(001 §3, `MCPDeliveryInfo`). The Drive `resource_ref` (webViewLink) still feeds
the email CTA. No new output keys; no schema change; no migration.

### Mechanism (informative — detail belongs in plan.md)

- Folder resolution runs **inside `drive_server._handle_upload`**, because only
  there is an authenticated Drive `service` available and the correct Drive
  (per-user vs central) is already selected by `token_path`. The server does a
  find-or-create: query
  `mimeType='application/vnd.google-apps.folder' and name='<folder>' and trashed=false`
  (ordered `createdTime` so "first" is the oldest, deterministically), reuse the
  first match, else create a folder. `DriveUploadRequest` gains a
  `folder_name: Optional[str]` field passed through `upload_report_to_drive`.
- **The resolved folder id is then threaded through the *rest* of the existing
  flow**: the current name-match `q` query (which decides update-vs-create,
  `drive_server.py:45-46`) MUST be scoped to that resolved id
  (`'<resolvedId>' in parents`), and the file create MUST set
  `parents=[<resolvedId>]`. Both the found/created folder and an explicit
  `MCP_DRIVE_FOLDER_ID` flow into the *same* scoping point, so overwrite
  semantics are identical across all folder paths (AC-4, AC-6a, AC-11).
- The human-readable `file_name` is computed in the delivery orchestrator and
  passed as the existing `file_name` argument (which today is `path.name`).

## Acceptance criteria

Each is written to become a direct test case. Server-touching criteria are unit
tested against `_handle_upload` with a faked Drive `service` (as existing
`drive_server` tests do); orchestrator criteria against `_deliver_drive` /
`deliver_report` with a stubbed `upload_report_to_drive`.

**Foldering**

- **AC-1** When `MCP_DRIVE_FOLDER_NAME="ContractSentinel"`, `MCP_DRIVE_FOLDER_ID`
  is `None`, and **no** folder named "ContractSentinel" exists, `_handle_upload`
  issues a folder **create** (`mimeType=application/vnd.google-apps.folder`,
  `name="ContractSentinel"`) and then creates the file with `parents=[<new
  folder id>]`.
- **AC-2** When such a folder **already exists**, `_handle_upload` reuses its id
  (no folder create) and uploads the file with `parents=[<existing id>]`.
- **AC-3** When multiple folders named "ContractSentinel" exist (user created a
  duplicate), the folder query orders by `createdTime` and the **oldest** match is
  reused deterministically across runs; no new folder is created.
- **AC-4** When `MCP_DRIVE_FOLDER_ID` is explicitly set (non-`None`), **no**
  find-or-create query runs and that id is used as the resolved folder for **both**
  the name-match `q` query (`'<id>' in parents`) and the file create
  `parents=[<id>]` (precedence over `MCP_DRIVE_FOLDER_NAME`; overwrite semantics
  preserved).
- **AC-6a** For every folder path (found, newly created, or explicit
  `MCP_DRIVE_FOLDER_ID`), the name-match `q` query that decides update-vs-create is
  scoped to the **resolved** folder id (`'<resolvedId>' in parents`) and is **not**
  left unscoped/root. This is what makes a same-`document_id` re-run overwrite the
  in-folder file (AC-11) rather than create a duplicate or match a same-named file
  elsewhere in the Drive.
- **AC-5** When `MCP_DRIVE_FOLDER_NAME` is `None`/`""` **and** `MCP_DRIVE_FOLDER_ID`
  is `None`, the file is uploaded to root with `parents=[]` (exact pre-033
  behavior).
- **AC-6** The find-or-create applies identically on the per-user path
  (`token_path` = a user token) and the central path (`token_path` = the central
  token) — the folder is created in whichever Drive the token authenticates.

**Human-readable naming**

- **AC-7** With `MCP_DRIVE_HUMAN_READABLE_NAMES=True`,
  `original_filename="Acme MSA.pdf"`, and `document_id` starting `a3f1c9…`, the
  PDF is uploaded to Drive as `Acme MSA — Risk Report (a3f1c9).pdf` and the JSON
  sibling as `Acme MSA — Risk Report (a3f1c9).json` (extension per format;
  `{stem}` = original name minus its extension; `{disc}` = Decision-1
  discriminator, first `MCP_DRIVE_NAME_DISCRIMINATOR_CHARS` of `document_id`).
- **AC-8** The **local** report files on disk keep their `document_id`-based
  names (`report_path` and its `.json`/`.pdf` siblings are unchanged) — only the
  Drive-facing `file_name` differs.
- **AC-9** When `original_filename` is missing or blank (or sanitizes to empty),
  the `{stem}` falls back to the full `document_id`, yielding
  `{document_id} — Risk Report (a3f1c9).<ext>` (never an empty or
  extension-only name).
- **AC-10** With `MCP_DRIVE_HUMAN_READABLE_NAMES=False`, uploaded names revert to
  the pre-033 `path.name` (`{document_id}.pdf` / `.json`).
- **AC-11** The name carries a short `document_id` discriminator (Decision 1) so
  two **different** jobs that share the same `original_filename` produce
  **distinct** Drive files (no silent overwrite), while a re-run/resume of the
  **same** job (same `document_id`) maps to the **same** name and overwrites in
  place via the server's existing name-match `update` path. Example: two
  `NDA.pdf` jobs →`NDA — Risk Report (a3f1c9).pdf` and
  `NDA — Risk Report (b7e402).pdf`.

**Query-safety / sanitization**

- **AC-12** Any value interpolated into a Drive v3 `q` string (the resolved file
  name and the configured folder name) has its `q`-grammar metacharacters escaped
  per the Drive v3 rule: a literal backslash → `\\` and a literal single quote →
  `\'`, applied in that order. Concretely, `O'Brien Lease.pdf` produces a name
  segment `O\'Brien Lease...` inside the quoted `q` term, so
  `files().list(q=...)` stays syntactically valid and matches the intended file
  (a test asserts the exact escaped `q` string; no unhandled `HttpError` from a
  malformed query). Applies identically to the folder find query.
- **AC-13** Before a value is used as a Drive **file name** (the stored name, not
  the `q` term), path separators (`/`, `\`) and control characters (incl.
  newlines/tabs) are stripped/replaced, and the `{stem}` is capped at
  `MCP_DRIVE_NAME_MAX_STEM_CHARS`. Note escaping (AC-12) and name-stripping
  (AC-13) are **distinct** operations applied to different sinks (the `q` query
  vs. the stored file name).

**Non-regression**

- **AC-14** Gmail delivery is unaffected: subject/body/CTA still build, and the
  email still sends (attachment naming per Decision 4).
- **AC-15** All feature 030/031/032 behaviors are preserved: PDF-render fail-safe
  → md fallback, per-user vs central token routing, not-connected → Drive skipped
  + email still sent, central-token temp-file decrypt/cleanup.
- **AC-16** A folder find-or-create failure (e.g. `HttpError` on the folder
  query/create) is contained: `_handle_upload` catches it and returns
  `ToolOutcome(ok=False)` → `DeliveryResult(ok=False)`, so the Drive upload
  records `status=FAILED` with an error message and **never raises** out of
  `deliver_report`; Gmail still runs.
- **AC-17** A folder-resolution failure does **not** leak the decrypted OAuth
  token: because the new failure point is inside the server subprocess (not the
  orchestrator), the orchestrator's existing `finally` cleanups still run — the
  per-user `user_token_path` unlink (`delivery_step.py:242-246`) and the central
  `_central_is_temp` unlink (`delivery_step.py:284-290`) — leaving no plaintext
  temp token on disk after a failed Drive delivery.

## Edge cases

- **Duplicate "ContractSentinel" folders** — user manually made two folders with
  that exact name. Deterministic reuse of the first match (AC-3); we never create
  a third and never try to de-duplicate the user's Drive.
- **Folder create races** — two reports delivered near-simultaneously both find
  no folder and both create one → two folders. Accepted as benign; a later run
  reuses the oldest (Decision 3 notes this; no locking is introduced).
- **Blank / whitespace-only `original_filename`** — fall back to `document_id`
  (AC-9); after sanitization the stem must be non-empty (if sanitization empties
  it, fall back to `document_id`).
- **`original_filename` with no extension** (e.g. `Acme MSA`) — `{stem}` is the
  whole name; result `Acme MSA — Risk Report (a3f1c9).pdf` (discriminator still
  appended per Decision 1; AC-7 logic still holds).
- **Very long `original_filename`** — the Drive name is truncated to a bounded
  length (Drive's practical limit is generous; we cap the `{stem}` to a named
  `MCP_DRIVE_NAME_MAX_STEM_CHARS` to avoid pathological names — see plan).
- **Filename-collision across different contracts** — two different uploads share
  the same `original_filename`; without a discriminator the server's
  name-in-folder match would `update`/overwrite the first's Drive file. Fixed by
  Decision 1 (the `{disc}` `document_id` suffix makes the two names distinct).
- **Single quote / special chars in the folder name** — the configured
  `MCP_DRIVE_FOLDER_NAME` is escaped in the folder `q` query identically to the
  file name (AC-12 applies to both).
- **Folder query returns non-folder or trashed items** — the query already
  filters `mimeType=…folder and trashed=false`; still, only the `id` is used.
- **Retry exhaustion / timeout** — unchanged from 010: the existing
  `call_tool_with_retry` (`MCP_DELIVERY_TIMEOUT_SECONDS`,
  `MCP_DELIVERY_MAX_RETRIES`) governs the whole tool call, now inclusive of the
  extra folder find-or-create round-trips. On exhaustion the Drive result is
  `FAILED`; Gmail is independent (AC-16). The added folder round-trip increases
  per-upload latency slightly (constitution §9) — one extra list (+ at most one
  create) per upload; acceptable for a post-terminal step.
- **Central token absent** — pre-existing guard: no central token → central
  Drive path fails as today; foldering/naming code is never reached.

## Out of scope

- **Any LangGraph node/edge, `ContractState`, or migration change** — none occur;
  this is delivery-only (constitution §2, §10). If that turns out false, STOP and
  amend `001` first.
- **Per-user *Gmail*** — Gmail stays central (constitution 031 amendment). Only
  Drive foldering/naming changes here.
- **Folder sharing, permissions, nested subfolders, per-contract subfolders, or
  organizing existing files** — out of scope; a single flat "ContractSentinel"
  folder only. RBAC/sharing remain PERMANENTLY CUT.
- **Renaming/moving reports already delivered to root before this feature** — no
  backfill or migration of historical Drive files.
- **Changing the on-disk report file names / `REPORT_*_FILENAME_TEMPLATE`** — the
  local artifacts and `report_path` stay `document_id`-based (feature 009 owns
  those); only the Drive/email-facing names change.
- **Encryption, Zero-Storage, retention** — remain Phase-2-DEFERRED.

## Resolved decisions

All open questions were resolved inline (owner preference for inline decisions
with rationale rather than blocking prompts). No open questions remain.

1. **Cross-contract name collision → append a `document_id` discriminator
   (always).** The name template includes `({disc})` where `{disc}` is the first
   `MCP_DRIVE_NAME_DISCRIMINATOR_CHARS` (default 6) of `document_id` (AC-7,
   AC-11). Rationale: every analysis job has a distinct `document_id`, so this
   guarantees two different jobs with the same `original_filename` become
   **distinct** Drive files (no silent overwrite / data loss), while a
   re-run/resume of the *same* job (same `document_id`) overwrites in place. It is
   deterministic and needs **no** extra Drive query (vs a "only when a collision
   exists" scheme, which would). The minor cosmetic cost of the suffix is accepted
   in exchange for never losing a prior report. Reversible via
   `MCP_DRIVE_HUMAN_READABLE_NAMES=False`.

2. **Name template + JSON sibling → `"{stem} — Risk Report ({disc})"`, rename
   both.** Em-dash separator, literal "Risk Report" wording. The `.json` sibling
   is renamed to match so the user sees a coherent matched pair in Drive
   (AC-7). Wording lives in `MCP_DRIVE_REPORT_NAME_TEMPLATE` so it is tunable
   without code change (constitution §3).

3. **Folder precedence & default → as specified.** `MCP_DRIVE_FOLDER_NAME`
   defaults to `"ContractSentinel"`; an explicitly set `MCP_DRIVE_FOLDER_ID` wins
   and skips find-or-create (AC-4); the benign duplicate-folder create race is
   accepted (no locking — first match reused on any later run, AC-3).

4. **Gmail attachment filename → renamed too.** The emailed attachment uses the
   same human-readable name via the shared naming helper, so the Drive file and
   the email attachment match (AC-14 covers non-regression of send). Reverts with
   the same `MCP_DRIVE_HUMAN_READABLE_NAMES` toggle.

5. **Sanitization policy → escape + strip + cap.** Two distinct operations on two
   distinct sinks: (a) for the Drive `q` query, escape `\` → `\\` then `'` → `\'`
   per the Drive v3 grammar (folder and file name alike, AC-12); (b) for the
   stored file name, strip path separators (`/`, `\`) and control chars and cap
   `{stem}` at `MCP_DRIVE_NAME_MAX_STEM_CHARS` (default 120) (AC-13). If
   sanitization empties the stem, fall back to `document_id` (AC-9).

## Open questions

None — all five original open questions were resolved inline (see **Resolved
decisions** above). This spec is considered final pending review approval.
