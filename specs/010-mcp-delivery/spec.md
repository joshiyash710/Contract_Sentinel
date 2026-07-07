# MCP Delivery Specification

> Feature 010 — the **MCP delivery step**: the post-pipeline transport layer that
> takes the report artifact ReportAgent (Node 7, feature 009) wrote to disk and
> delivers it to the user via **Google Drive** and **Gmail** — the *only* two MCP
> integrations the constitution permits (§2 PERMANENTLY CUT: "Slack, Notion, or any
> MCP integration beyond Drive + Gmail").
>
> **This is NOT an 8th graph node.** Constitution §2 fixes the LangGraph StateGraph
> at *exactly* 7 sequential nodes + exactly 2 conditional edges, terminating at
> `report → END` (feature-009 §7.1, `builder.py:133`). `001` §3 deliberately labels
> `mcp_delivery_status` "**Added by MCP delivery step**" — a *step*, not a node. This
> feature therefore adds a **standalone callable** invoked *after* the compiled graph
> returns, and makes **zero** changes to `builder.py`, preserving the
> "exactly 7 nodes / exactly 2 conditional edges" invariant (D1).
>
> **Design decisions resolved with rationale in §8a (D1–D13).** Feature-009 D7 pinned
> that delivery is feature 010, out of Node-7 scope; feature-008 §5.9 and 009 §5.1
> both point here. The **transport architecture is pinned in D10** — the step is an
> MCP client to local Drive/Gmail MCP servers wrapping `google-api-python-client`, per
> `002` §g — and the prior open questions Q1–Q3 are resolved in **D11–D13**. **§8b now
> lists no remaining open questions**; this spec is ready for plan.md.

## 1. Problem Statement

The 7-node pipeline ends at ReportAgent (Node 7), which writes a Markdown report +
JSON sibling under `data/reports/{document_id}.{md,json}` and puts `report_path`
(the Markdown path) into `ContractState` (feature-009 §2.2, D1/D6). At that point the
deliverable **exists on disk but has not left the machine.** Nothing in the fixed
7-node graph is responsible for getting it to a human — by design: constitution §2
lists delivery nowhere among the 7 nodes, and reserves it instead as a separate
"MCP delivery step" (`001` §3, `mcp_delivery_status`).

**This feature is that step.** It reads the artifact Node 7 produced (`report_path`
+ its JSON sibling) and delivers it over the two — and only two — MCP channels the
constitution permits:

1. **Google Drive** — uploads the report file(s) to the user's Drive so they have a
   durable, shareable copy.
2. **Gmail** — sends the user an email summarizing the run's findings, attaching the
   Markdown report and (when the Drive upload succeeded) linking to the Drive copy.

It then records the outcome **per channel** in `mcp_delivery_status`
(`001` §3: `Dict[str, MCPDeliveryInfo]`, `merge_dicts` reducer).

**Where it sits in the fixed architecture.** It runs **after** `report → END`. The
compiled graph returns a terminal `ContractState`; the delivery step is a pure
consumer of that state's `report_path` (and the header/summary fields it needs for
the email). It is **transport only** — it never re-reads `clauses`, never re-renders
the report, never re-judges/re-scores/re-retrieves anything (that is Nodes 3–7's
job, already done and frozen in the artifact). Contrast with Node 7, which *assembles*
the artifact; this step *ships* it.

**Not a node → no graph wiring change (D1).** Because it is a post-terminal step, this
feature adds **no** `graph.add_node` / `graph.add_edge` / `graph.add_conditional_edges`
call. `builder.py` is untouched. The step is a standalone function,
`deliver_report(state, ...) -> dict`, that a future runner/API layer invokes once the
graph run completes. **No runner exists yet** (feature-009 D2 integration caveat: at
time of writing there is no graph-runner / API-invocation layer). This feature ships
the callable + its MCP clients + a documented integration contract for that future
runner; wiring the trigger into an actual request flow is the runner feature's job
(§5.5).

**Transport = MCP, not raw Google calls (D10).** Per `002` §g — which lists the `mcp`
Python SDK *alongside* `google-api-python-client` and pins integration "via the Model
Context Protocol" — the delivery step is an **MCP client**. It opens a session to a
local **Drive MCP server** and **Gmail MCP server** (thin wrappers this feature builds
around `google-api-python-client` + Google OAuth) and invokes their tools (an
upload-file tool, a send-message tool). The Google OAuth credentials live at the
**server** boundary, not in the delivery step, which never touches raw Google HTTP
directly. This keeps the `mcp` dependency load-bearing (not dead weight) and the
"MCP delivery" name literal, and requires **no** change to `002` (the OAuth + MCP
stack it lists already covers this — §5.9). MCP server transport (stdio), tool schemas,
and session lifecycle are plan.md detail; the spec pins only that delivery goes
*through* MCP.

**Boundary crossing → Pydantic + explicit timeout/retry (constitution §4, §9).** Every
MCP tool call crosses a system boundary (client → server → Google API → back). Per §4,
the request/response payloads that cross that boundary are modeled with **Pydantic**,
not TypedDict. Per §9, each tool call — like the Ollama calls in Nodes 3–6 — gets an
**explicit per-attempt timeout and a bounded, backed-off retry** rather than assuming
sub-second responses; a hung upload/send must never hang the delivery step (§7.5).

**Best-effort, per-channel, non-fatal (D3).** Delivery runs *after* the pipeline has
already produced its deliverable on disk. A failed upload or email must therefore
never lose the report or crash anything: each channel records its own success/failure
in `mcp_delivery_status`, independently, and one channel failing never blocks or
reverts the other. The report file on disk is the source of truth; delivery is a
best-effort convenience on top of it.

## 2. Inputs and Outputs

All fields reference `ContractState` as defined in
`specs/001-contract-state-schema.md`. **This spec introduces no new `ContractState`
field names.** The only key it writes — `mcp_delivery_status` — is already reserved in
`001` §3 (under the `# Added by MCP delivery step` comment) with its
`Annotated[Dict[str, MCPDeliveryInfo], merge_dicts]` type and `MCPDeliveryInfo`
shape. Any Pydantic model this feature defines for the Drive/Gmail request/response
payloads is a *transport* type that lives **outside** graph state (constitution §4),
never a state field.

### 2.1 Reads from `ContractState`

- `report_path`: `Optional[str]` — **the primary input.** The Markdown report path
  ReportAgent wrote (feature-009 §2.2). The step delivers this file; its JSON sibling
  is derived by swapping the stem's extension (feature-009 D1: same stem, `.json`).
  If `report_path is None` (Node 7's write failed, feature-009 AC-19) the step has
  nothing to deliver → Edge Case 1.
- `document_id`: `str` — used for the deterministic Drive filename and the email
  subject/identity.
- `original_filename`: `str` — shown in the email subject/body ("report for
  `<original_filename>`").
- `ingest_error`: `Optional[Dict[str, str]]` — checked defensively: if the pipeline
  short-circuited on ingest (`builder.py:59-66`), Node 7 still wrote a minimal
  "could not process" report (feature-009 AC-20), so delivery still has a valid
  `report_path` to ship — it delivers the minimal report unchanged (Edge Case 6).
- **Report summary counts for the email body** are read from the **JSON sibling on
  disk**, not from `ContractState` — the per-finding roll-up (`total_clauses`,
  `validated_findings`, `clean_clauses`, `high`/`medium`/`low`) lives in
  `ContractReport.summary` (feature-009 `models/report.py`), which Node 7 already
  serialized. Reading it from the JSON avoids re-deriving counts from `clauses` and
  keeps this step pure transport (D5). If the JSON sibling is missing/unreadable, the
  email falls back to a generic subject/body without counts (Edge Case 4).

The step does **not** read `clauses`, `evidence_trail`, risk fields, or any per-clause
data (D5). It is transport, not presentation.

### 2.2 Writes to `ContractState`

Per the partial-update rule (constitution §5) the step returns **only** the key(s) it
updates:

| Field | Type | Reducer (per `001`) | Description |
|-------|------|---------------------|-------------|
| `mcp_delivery_status` | `Dict[str, MCPDeliveryInfo]` | `merge_dicts` | One entry **per attempted channel**, keyed by the service name — the literals `"drive"` and `"gmail"`. Each value is an `MCPDeliveryInfo` = `{status: MCPDeliveryStatus, error_message: Optional[str], delivered_at: Optional[str]}` (`001` §3). This step writes only `MCPDeliveryStatus.SUCCESS` or `FAILED` — **never `PENDING`**, which `001` reserves for a possible future async/queued runner (D11a). `delivered_at` = ISO timestamp on success (else `None`); `error_message` = a short reason on failure (else `None`). A **config-disabled** channel contributes **no** entry (it was not attempted); an **enabled-but-cannot-proceed** channel records a `FAILED` entry (D13). Because the reducer is `merge_dicts`, a re-delivery updates the per-service entry in place. |

**It writes nothing else.** In particular it does **not** write:
- `current_node` — it is a **step, not a node** (D1); pinning a node name here would
  imply an 8th node and is exactly what §2 forbids. `current_node` remains `"report"`
  (the true terminal node).
- `node_timings` — the step writes **no** entry here (D11): that dict's `001` gloss is
  literally "**Node** → seconds" and this is not a node. Its wall-clock time is emitted
  to structured logs only.
- `processing_completed_at` — runner-owned (feature-009 D2); delivery does not stamp
  the pipeline's completion time.
- `report_path`, `evidence_trail`, or any Node 1–7 key.

**Error accounting (D8).** A delivery failure is recorded **only** in the failing
channel's `mcp_delivery_status` entry (`status = FAILED`, `error_message` set) — it
does **NOT** increment `error_count`. `error_count` is the *in-graph* pipeline-health
counter (Nodes 4–7 emit it while the graph runs); the delivery step runs *after* the
graph has already returned its terminal state, so folding post-graph transport
failures into the in-graph health counter would conflate two different lifecycles.
Delivery health is fully captured, per channel, in `mcp_delivery_status`.

### 2.3 What is delivered

- **Drive (D2):** calls the Drive MCP server's upload tool to upload the report
  file(s) named by `MCP_DRIVE_UPLOAD_FORMATS`
  (default: both the Markdown and the JSON sibling) into the folder identified by
  `MCP_DRIVE_FOLDER_ID` (default: the account's Drive root). The uploaded file's name
  is deterministic on `document_id` (mirrors Node 7's `{document_id}.{md,json}`), so a
  re-run overwrites/updates the same-named file rather than proliferating copies
  (D6). On success the step captures the returned Drive file id/URL **in memory** for
  the Gmail body; it is **not** persisted in state (D12).
- **Gmail (D2):** calls the Gmail MCP server's send tool to send one email to
  `MCP_DELIVERY_RECIPIENT` with:
  - **Subject** — identifies the contract and headline counts, e.g.
    `"ContractSentinel report — <original_filename>: N findings (H high / M med / L low)"`
    (counts from the JSON summary; generic subject if unavailable — Edge Case 4).
  - **Body** — a short human summary of the run (counts) plus, **when the Drive
    upload succeeded**, a link to the Drive copy. If Drive failed/was disabled, the
    body omits the link and relies on the attachment.
  - **Attachment** — the Markdown report file, attached directly when
    `MCP_GMAIL_ATTACH_REPORT` is true (default), so the recipient always has the
    report even if the Drive link is absent or its permissions are not shareable
    (D3 robustness).

## 3. Acceptance Criteria

Each criterion is written to become a test case directly. All Google Drive/Gmail
network calls are **mocked** (no live Google account, no real OAuth) — the tests
assert the step's *behavior* (which client methods it calls, with what payload, and
how it maps outcomes into `mcp_delivery_status`), not Google's behavior. File reads
run against a temp directory (`tmp_path`) holding a fixture Markdown + JSON pair.

### Delivery behavior

1. **Both channels attempted on the happy path**: Given a valid `report_path` (file
   exists) with both channels enabled, the step calls the Drive upload client **and**
   the Gmail send client exactly once each, and returns a `mcp_delivery_status` with
   both a `"drive"` and a `"gmail"` entry, each `status == SUCCESS` with a non-`None`
   `delivered_at` and `error_message is None`.

2. **Drive uploads the configured formats**: With `MCP_DRIVE_UPLOAD_FORMATS`
   defaulting to both, the Drive client is asked to upload two files — the Markdown at
   `report_path` and the JSON sibling at the same stem. With the config set to
   Markdown-only, exactly one upload (the `.md`) occurs.

3. **Drive filename is deterministic on `document_id`**: The name passed to the Drive
   upload equals the basename Node 7 already wrote — `Path(report_path).name`
   (`{document_id}.md`) and its `.json` sibling — so a re-delivery targets the
   same-named Drive file (D6). (The step reuses Node 7's on-disk basenames; it does not
   re-import Node 7's filename templates.)

4. **Gmail is addressed, subjected, and attached correctly**: The Gmail send is
   called with `to == MCP_DELIVERY_RECIPIENT`, a subject containing
   `original_filename` and the finding counts, and — when `MCP_GMAIL_ATTACH_REPORT` is
   true — the Markdown file as an attachment.

5. **Gmail body links to Drive only when Drive succeeded**: When the Drive upload
   returns a file URL, the email body contains that URL. When Drive failed or is
   disabled, the body contains **no** Drive link but the email is still sent (with the
   attachment).

6. **Summary counts come from the JSON sibling**: The email subject/body counts equal
   the `summary` counts in the JSON sibling on disk (feature-009 `ReportSummary`),
   not re-derived from `clauses` (which the step never reads).

### State outputs

7. **`mcp_delivery_status` keyed by service**: The returned dict's
   `mcp_delivery_status` has keys drawn only from `{"drive", "gmail"}`, and each value
   has exactly the `MCPDeliveryInfo` keys `status`, `error_message`, `delivered_at`
   (`001` §3) and no others.

8. **`MCPDeliveryStatus` enum values used**: Each entry's `status` is a
   `MCPDeliveryStatus` member, never a bare string inconsistent with `001`. This step
   only ever writes `SUCCESS` or `FAILED`; **no code path produces `PENDING`** (D11a) —
   a test asserts `PENDING` never appears in a returned `mcp_delivery_status`.

9. **Disabled channel contributes no entry**: With `MCP_DRIVE_ENABLED = False`, the
   step does not call the Drive client and `mcp_delivery_status` has **no** `"drive"`
   key (only `"gmail"`). Symmetrically for `MCP_GMAIL_ENABLED = False`.

10. **Partial update only**: The returned dict contains **only** `mcp_delivery_status`.
    It contains **no** `current_node`, **no** `node_timings` entry (D11), **no**
    `processing_completed_at`, **no** `error_count`, and no Node 1–7 key.

11. **`error_count` untouched on failure (D8)**: When a channel fails, the returned
    dict does **not** contain `error_count`; the failure appears only as
    `status == FAILED` + `error_message` in that channel's entry.

### Independence & failure isolation

12. **Drive failure does not block Gmail**: If the Drive client raises, the step still
    attempts Gmail; `mcp_delivery_status["drive"].status == FAILED` (with
    `error_message`) while `mcp_delivery_status["gmail"].status == SUCCESS`. The step
    does not raise.

13. **Gmail failure does not revert Drive**: If Gmail raises after a successful Drive
    upload, `"drive"` stays `SUCCESS` and `"gmail"` is `FAILED`; no attempt is made to
    delete/roll back the Drive file (best-effort, D3).

14. **Total failure is non-fatal**: If **both** channels raise, the step returns a
    `mcp_delivery_status` with both entries `FAILED` and **does not raise** — the
    caller (future runner) still gets a clean return value.

### Config, timeout, retry

15. **All toggles/paths/recipient read from config**: Channel enables, recipient,
    Drive folder, upload formats, timeout, and retry count are read from `app.config`
    constants (constitution §3), never hardcoded inline. Recipient is overridable via
    an env var (D4).

16. **Per-attempt timeout enforced**: Each MCP tool call is issued with the
    `MCP_DELIVERY_TIMEOUT_SECONDS` deadline as a **per-attempt** budget; an attempt that
    exceeds it is treated as a failed attempt (not a hang, constitution §9). Combined
    with retries, a channel's worst-case latency is bounded at roughly
    `(1 + MCP_DELIVERY_MAX_RETRIES) × MCP_DELIVERY_TIMEOUT_SECONDS`, and after the last
    attempt the channel is marked `FAILED` with a timeout `error_message`.

17. **Bounded, backed-off retry on transient errors**: A transient error the MCP server
    surfaces (wrapping a Google HTTP 5xx / rate-limit) is retried up to
    `MCP_DELIVERY_MAX_RETRIES` times **with exponential backoff** before the channel is
    marked `FAILED`; a non-retryable error (e.g. auth/permission, malformed request)
    fails the channel immediately without retry. The retry count is a config constant.

### Degenerate & guard paths

18. **No `report_path` → nothing delivered, recorded as failed/skipped**: If
    `report_path is None` (Node 7 write failed, feature-009 AC-19), the step makes
    **no** Drive/Gmail call and records the intended channels as `FAILED` with an
    `error_message` explaining there was no artifact to deliver (Edge Case 1). It does
    not raise.

19. **Missing report file on disk**: If `report_path` is set but the file does not
    exist on disk (deleted/moved between Node 7 and delivery), each enabled channel is
    marked `FAILED` with a "report file not found" `error_message`; no partial upload
    is attempted (Edge Case 2).

20. **Missing recipient → Gmail `FAILED`, Drive proceeds**: If `MCP_DELIVERY_RECIPIENT`
    is empty and no per-call override is given, Gmail is **not** sent and records a
    `FAILED` entry with a "no recipient configured" `error_message` (D13 — an
    *enabled* channel that cannot proceed is `FAILED`, not silently skipped), while
    Drive still uploads normally (Edge Case 3).

21. **Missing/unreadable JSON sibling → generic email still sent**: If the JSON
    sibling is absent/corrupt, the email is still sent with a generic subject/body
    (no counts) and the Markdown attachment; `"gmail"` is `SUCCESS`, not `FAILED`
    (Edge Case 4).

22. **Re-delivery is idempotent on state shape**: Running the step twice on the same
    terminal state produces a `mcp_delivery_status` with the same two keys; because
    the reducer is `merge_dicts`, the second run's per-service entries replace the
    first's rather than duplicating (Edge Case 7).

## 4. Edge Cases

1. **`report_path is None`** (Node 7's write failed upstream, feature-009 AC-19):
   there is no artifact to deliver. Record each intended channel as `FAILED` with a
   clear reason; make no network call; do not raise (AC-18).

2. **`report_path` set but file missing on disk** (deleted/moved between Node 7 and
   delivery): mark enabled channels `FAILED` ("report file not found"); no partial
   upload (AC-19).

3. **No recipient configured** (`MCP_DELIVERY_RECIPIENT` empty, no override): Gmail
   cannot be sent; record it `FAILED` with a "no recipient configured" reason (D13) and
   still upload to Drive (AC-20).

4. **JSON sibling missing/corrupt**: the email loses its summary counts but is still a
   valid deliverable (Markdown attached); send it with a generic subject/body — not a
   failure (AC-21). Drive is unaffected (it uploads whatever report files exist).

5. **Drive upload succeeds but returns no shareable URL** (permissions/scoping): the
   Gmail body omits the link and relies on the attachment; `"drive"` is still
   `SUCCESS` (the file *was* uploaded). Do not fail Drive just because a link/permission
   couldn't be produced.

6. **`ingest_error` was set upstream**: Node 7 wrote a *minimal* "could not process"
   report (feature-009 AC-20) and set `report_path`; delivery ships that minimal
   report unchanged. Delivery does not special-case ingest failures — a delivered
   "could not process" notice is a legitimate outcome the user should receive.

7. **Re-delivery / re-run**: a second delivery of the same `document_id` overwrites the
   same-named Drive file (D6) and resends the email; `mcp_delivery_status`'s
   `merge_dicts` reducer updates the per-service entries in place (AC-22).

8. **Transient vs. permanent error surfaced by the MCP server**: a transient failure
   the server wraps (Google 5xx / rate-limit) is retried up to
   `MCP_DELIVERY_MAX_RETRIES` with backoff (AC-17); a permanent failure it wraps
   (auth/permission 401/403, malformed 4xx) fails the channel immediately — retrying it
   would only burn the timeout budget (constitution §9). The server preserves the
   retryable-vs-permanent classification in the tool result it returns to the client.

9. **OAuth token missing/expired/unauthorized**: the credential lives at the MCP
   server layer (D10); if it is missing/expired the server surfaces an auth error, which
   the step maps to a `FAILED` entry with an auth `error_message`. The step never
   attempts an interactive OAuth consent flow at runtime (a one-time setup concern —
   §5.4) and does not crash. If Drive and Gmail share one credential, both fail with the
   same reason.

10. **Both channels disabled** (`MCP_DELIVERY_ENABLED = False` or both sub-toggles
    off): the step is a no-op — it returns an empty `mcp_delivery_status` (no entries),
    makes no network call, and does not raise. Delivery is an opt-in convenience, and a
    deployment may legitimately run the pipeline with delivery off.

11. **Very large report attachment**: a report exceeding Gmail's attachment size limit
    causes the Gmail send to fail; record `"gmail"` `FAILED` with a size
    `error_message`. Mitigation (link-only when oversized) is deferred (§5.6). Drive is
    unaffected.

## 5. Out of Scope

The MCP delivery step does **NOT** handle:

1. **Being a graph node / any change to `builder.py`** — it is a post-terminal step,
   not one of the fixed 7 nodes (constitution §2; D1). The graph still ends at
   `report → END`. Wiring the 7-node invariant is owned by feature-009's builder.

2. **Assembling or rendering the report** — that is ReportAgent (Node 7,
   `specs/009-*`). This step ships the artifact Node 7 produced and never re-renders,
   re-scores, re-validates, or re-retrieves (D5). If the *content* of the report needs
   to change, that is a Node-7 change, not a delivery change.

3. **Any MCP integration other than Google Drive and Gmail** — Slack, Notion, and every
   other integration are PERMANENTLY CUT (constitution §2). Calendar/Sheets/etc. are
   equally out; Drive + Gmail are the whole scope.

4. **One-time OAuth setup / consent flow / credential provisioning** — obtaining and
   storing the Google OAuth token (the interactive consent that produces the token
   file the step reads) is a deployment/setup concern, not a per-delivery runtime
   concern. The step *reads* an already-provisioned credential and fails gracefully if
   it is missing/expired (Edge Case 9). The setup procedure/tooling is documented in
   plan.md, not implemented as pipeline logic.

5. **The trigger / runner / API layer that invokes this step** — *when* delivery runs
   (after every run, on user opt-in, via an API endpoint) is owned by the future
   runner/API feature (feature-009 D2 integration caveat). This feature ships the
   callable and its integration contract; it does not decide or implement the trigger
   policy.

6. **Attachment-size fallback, retention, and history** — chunking/oversized handling
   beyond a graceful failure (Edge Case 11), Drive versioning/retention, and delivery
   history/audit are Phase-2 concerns (constitution §2 PHASE-2-DEFERRED "Retention
   policy"; PERMANENTLY-CUT "audit log UI/dashboard/viewer").

7. **Per-user / multi-tenant recipient management** — RBAC and multi-tenant access are
   PERMANENTLY CUT. Phase 1 uses a single configured recipient (D4).

8. **Persisting the Drive file URL / Gmail message id in `ContractState`** — resolved
   **not** to in Phase 1 (D12): `MCPDeliveryInfo` stays `{status, error_message,
   delivered_at}` (no `resource_ref`), so no constitution §10 schema change to `001`.
   The Drive URL is used in-memory for the email body and emitted to logs; persisting a
   resource reference is a future refinement once a consumer for it (e.g. a UI
   "view in Drive" link) exists.

9. **Any change to `002-tech-stack.md`** — the OAuth stack (`google-auth`,
   `google-auth-oauthlib`, `google-auth-httplib2`, `google-api-python-client`) and the
   `mcp` SDK this feature uses are already listed in `002` §g (deps at lines 143–148).
   This feature adds only *application* code + config; it introduces no new dependency
   and requires no tech-stack revision.

## 6. Configurable Constants

Per constitution §3, all thresholds/paths/toggles live in `backend/app/config.py`.
This spec adds a new `# ── MCP delivery` section. The exact values below are
**proposed defaults**; the ones flagged in §8b (recipient handling, formats) may shift
with the open questions.

```python
# ── MCP delivery ───────────────────────────────────────────────────────────────
# Source: specs/010-mcp-delivery/spec.md §6

MCP_DELIVERY_ENABLED: bool = True
# Master switch. False → the delivery step is a no-op (Edge Case 10).

MCP_DRIVE_ENABLED: bool = True
MCP_GMAIL_ENABLED: bool = True
# Per-channel toggles. A disabled channel is never attempted and contributes no
# mcp_delivery_status entry (AC-9). Both off ≡ MCP_DELIVERY_ENABLED False.

MCP_DELIVERY_RECIPIENT: str = ""
# Default Gmail recipient. Overridable via the CONTRACTSENTINEL_DELIVERY_RECIPIENT
# environment variable (concrete name — AC-15 asserts on it); a future runner may also
# override per request (D4). Empty → Gmail records a FAILED entry with a
# "no recipient configured" reason while Drive still proceeds (D13, Edge Case 3).

MCP_DRIVE_FOLDER_ID: Optional[str] = None
# Target Drive folder id. None → the account's Drive root.

MCP_DRIVE_UPLOAD_FORMATS: tuple = ("md", "json")
# Which of Node 7's report files to upload. Default both (Markdown + JSON sibling);
# ("md",) uploads only the human-readable Markdown (AC-2).

MCP_GMAIL_ATTACH_REPORT: bool = True
# Attach the Markdown report to the email so the recipient always has it even without
# a shareable Drive link (D3 robustness, AC-4).

MCP_DELIVERY_TIMEOUT_SECONDS: int = 60
# Per-ATTEMPT wall-clock timeout for one MCP tool call (client→server→Google→back),
# constitution §9. Exceeding it fails that attempt; combined with retries a channel's
# worst case is bounded at ~(1 + MCP_DELIVERY_MAX_RETRIES) × this value, never a hang
# (AC-16).

MCP_DELIVERY_MAX_RETRIES: int = 2
# Bounded retries WITH EXPONENTIAL BACKOFF for TRANSIENT errors the MCP server surfaces
# (Google 5xx / rate-limit) before a channel is marked FAILED. Non-retryable errors
# (auth/permission/malformed) fail immediately without retry (AC-17, Edge Case 8).

GOOGLE_OAUTH_CREDENTIALS_PATH: str = "data/secrets/google_credentials.json"
GOOGLE_OAUTH_TOKEN_PATH: str = "data/secrets/google_token.json"
# backend/-relative paths to the OAuth client-secrets file and the cached user token.
# Consumed by the Drive/Gmail MCP SERVER layer (which wraps google-api-python-client),
# NOT by the delivery-step client directly (D10). Setup/consent that produces the token
# is out of scope (§5.4). Both live under a git-ignored secrets dir; never committed.
# The OAuth + MCP stack these rely on is already in 002 §g — no tech-stack change (§5.9).
```

There is intentionally **no** LLM/model constant here — the delivery step, like
ReportAgent, makes **zero** LLM calls; it is pure transport.

## 7. Pinned Design (safe for plan.md)

These follow directly from the constitution / shared conventions and are safe to plan
against regardless of how the Open Questions (§8b) resolve:

### 7.1 Post-terminal step, not a node, no graph change
The step is a standalone `deliver_report(state, ...) -> dict` invoked after the
compiled graph returns. `builder.py` is untouched; the graph still has exactly 7 nodes
and 2 conditional edges, ending at `report → END` (constitution §2; AC-10 asserts no
node-owned keys are written).

### 7.2 Drive + Gmail only
The two — and only two — channels the constitution permits (§2 PERMANENTLY CUT). No
other MCP integration is added, now or by extension (§5.3).

### 7.3 Per-channel, best-effort, non-fatal
Each channel writes its own `mcp_delivery_status[service]` entry; a failure in one
never blocks/reverts the other and never raises (D3; AC-12/13/14). The on-disk report
is the source of truth; delivery is best-effort on top.

### 7.4 `mcp_delivery_status` is the only state write
Keyed by `"drive"`/`"gmail"`, `MCPDeliveryInfo` shape per `001` §3, `merge_dicts`
reducer. No `current_node`, no `processing_completed_at`, no `error_count`, no Node
1–7 key (D8; AC-10/11).

### 7.5 MCP client + Pydantic + explicit timeout/retry at the boundary
Delivery is an MCP client to local Drive/Gmail MCP servers wrapping
`google-api-python-client` (D10). MCP tool request/response payloads are Pydantic
transport types (never stored in state, constitution §4); every tool call carries a
**per-attempt** `MCP_DELIVERY_TIMEOUT_SECONDS` and a bounded, backed-off
`MCP_DELIVERY_MAX_RETRIES`, so each channel's worst-case latency is explicit and
bounded (constitution §9; AC-16/17).

### 7.6 All toggles/paths/recipient in `app.config`
No hardcoded recipient, folder, format, timeout, or retry (constitution §3; AC-15).

## 8. Design Decisions and Open Questions

### 8a. Resolved / pinned (safe for plan.md)

- **D1 — Post-terminal step, NOT an 8th graph node; no `builder.py` change.**
  Constitution §2 fixes exactly 7 nodes / 2 conditional edges ending at
  `report → END`; `001` §3 labels this "the MCP delivery **step**". Realized as a
  standalone callable the future runner invokes after the graph returns. Preserves the
  §2 invariant absolutely.

- **D2 — Two channels: Drive upload + Gmail email; Gmail links to the Drive copy when
  available and always attaches the Markdown.** Drive gives a durable shareable copy;
  Gmail notifies the user with a findings summary. The attachment guarantees the report
  reaches the user even if the Drive link/permissions aren't shareable (robustness).

- **D3 — Per-channel, best-effort, independent, non-fatal.** Each service records its
  own `mcp_delivery_status` entry; one failing never blocks/reverts the other; the step
  never raises. Delivery runs after the artifact already exists on disk, so a transport
  failure must never lose the deliverable.

- **D4 — Recipient from a config/env default, runner-overridable.** No per-user auth
  layer exists yet, so a single configured `MCP_DELIVERY_RECIPIENT` (env-overridable)
  is the Phase-1 recipient; a future runner/API may pass a per-request override.
  Multi-tenant recipient management is PERMANENTLY CUT (§5.7).

- **D5 — Transport only; reads `report_path` + the JSON sibling, never `clauses`.** The
  step ships the frozen Node-7 artifact and reads summary counts from the already-
  serialized JSON, never re-deriving from per-clause state. Keeps the Node-7 /
  delivery boundary clean (contrast: Node 7 *assembles*, this step *ships*).

- **D6 — Deterministic Drive filename on `document_id`; re-delivery overwrites in
  place.** Mirrors Node 7's `{document_id}.{md,json}` scheme so a re-run updates the
  same Drive file rather than proliferating copies. History/versioning is Phase-2
  (§5.6).

- **D7 — Explicit per-call timeout + bounded retry on Google APIs.** Constitution §9's
  latency discipline applies to Google API calls exactly as it does to Ollama: a hung
  or rate-limited call fails its channel within a bounded budget rather than hanging
  the step (AC-16/17).

- **D8 — Delivery failures go to `mcp_delivery_status`, not `error_count`.**
  `error_count` is the in-graph pipeline-health counter (Nodes 4–7); the delivery step
  runs after the graph returns, so its failures are recorded per-channel in
  `mcp_delivery_status` instead, keeping the two lifecycles distinct.

- **D9 — OAuth consent/setup is out of scope; the step only reads a provisioned
  credential.** One-time interactive consent (producing the token file) is a
  deployment concern documented in plan.md; the runtime step reads the token and fails
  gracefully if it is missing/expired (Edge Case 9), never launching an interactive
  flow mid-pipeline.

- **D10 — Transport is MCP: the step is an MCP client to local Drive/Gmail MCP servers
  wrapping `google-api-python-client`.** `002` §g lists the `mcp` SDK *and* the Google
  client libs and pins integration "via the Model Context Protocol"; realizing delivery
  as raw Google calls would make the `mcp` dependency dead weight and contradict `002`.
  So this feature builds thin local **Drive** and **Gmail** MCP servers
  (`google-api-python-client` + OAuth at the server boundary) and the delivery step
  calls their tools as an MCP client. Google OAuth credentials live at the server layer,
  not the step. No `002` change is needed (the stack is already listed — §5.9). Server
  transport (stdio), tool schemas, and session lifecycle are plan.md detail; the spec
  pins only that delivery goes *through* MCP. *(Resolves review blocker #1.)*

- **D11 — No observability marker/timing written to state (resolves Q1 → option a).**
  The step writes neither `current_node` (not a node) nor a `node_timings` entry (that
  dict's `001` gloss is "**Node** → seconds" and this is not a node); its wall-clock
  time is emitted to structured logs only. State writes stay confined to
  `mcp_delivery_status` (§7.4). **D11a:** the step writes only
  `MCPDeliveryStatus.SUCCESS` or `FAILED` — never `PENDING`, which `001` reserves for a
  possible future async/queued runner and no code path here produces (resolves
  review #4).

- **D12 — Do not persist the Drive URL / Gmail message id in state (resolves Q2 →
  option a).** `MCPDeliveryInfo` stays `{status, error_message, delivered_at}`; no
  `resource_ref` field, hence no constitution §10 schema change to `001`. The Drive URL
  is used in-memory for the email and logged. A persisted resource reference is deferred
  until a consumer for it exists (§5.8).

- **D13 — Enabled-but-cannot-proceed → `FAILED` entry; config-disabled → no entry
  (resolves Q3 → option a, and review #3).** The single rule: a channel **disabled by
  config** (`MCP_DELIVERY_ENABLED`/`MCP_DRIVE_ENABLED`/`MCP_GMAIL_ENABLED` false) is
  never attempted and contributes **no** `mcp_delivery_status` entry (AC-9, Edge Case
  10); a channel that **was enabled but cannot run** at runtime (empty recipient, no
  artifact, missing file) records a **`FAILED`** entry with an `error_message`
  (AC-18/20, Edge Case 1/2/3). This makes "delivery was intended but couldn't happen"
  visible in state rather than silent, and removes the earlier AC-20 / Edge Case 3
  hedging.

### 8b. Open Questions

No remaining open questions. Review blocker #1 (transport) and the prior Q1–Q3 are
resolved in §8a (D10–D13); consistency fixes #3–#5 and polish #6–#7 are folded into
§2/§3/§4/§6/§5. This spec is final and ready for plan.md (constitution §1 / §8).
