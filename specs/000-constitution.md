# ContractSentinel Constitution

This document defines the non-negotiable rules and architectural constraints for the ContractSentinel project. All future development must adhere to these principles.

## 1. Spec-Driven Workflow Rule

For every feature, development follows this strict sequence:
1. **spec.md** (requirements) - Defines what the feature should do
2. **plan.md** (technical design) - Details how the feature will be implemented
3. **tasks.md** (implementation steps) - Numbered steps to execute the plan
4. **Implementation** - Actual coding based on the tasks

No file under `backend/app/` or `frontend/src/` may be written until that specific feature's spec.md AND plan.md exist and have been explicitly approved. If this rule appears to be at risk of violation, stop and ask rather than proceeding.

## 2. Fixed Architecture Rule

The LangGraph StateGraph has exactly 7 sequential nodes plus exactly 2 conditional edges. This is the complete, final scope for v1:

1. IngestAgent — parses PDF/DOCX, OCR fallback if text extraction fails
2. ClauseSplitterAgent — segments the parsed document into discrete clauses
3. CRAG retrieval — per clause, scores retrieval confidence:
   - score >= 0.73 -> Local clause KB (FAISS vector search)
   - score <  0.73 -> Live legal search (web fallback)
   - evidence merged per clause regardless of source path
4. Self-RAG validation — against merged evidence, runs:
   - Relevance check, ISREL check, ISSUP check ("worth flagging")
   - retry on ISSUP fail, max 3 attempts
   - outcome: "Discard finding" (never shown to user) or "Validated finding"
5. RiskScoreAgent — assigns Low/Medium/High risk to each validated finding
6. Conditional edge route_on_risk:
   - risk found -> RedlineAgent (drafts safer clause language)
   - no risk -> SkipRedline (clause marked clean)
7. ReportAgent — compiles final report + evidence trail

Only 2 conditional edges exist: CRAG's confidence-based routing, and route_on_risk. Every other transition is a plain linear add_edge.

**PHASE 2 DEFERRED** (Do not build, do not spec, do not let this leak into any Phase 1 file):
- PrivacyAgent — inserted between IngestAgent and ClauseSplitterAgent
- Encryption at rest — AES-256 via Python's `cryptography` (Fernet)
- Zero Storage mode — per-upload user choice for ephemeral processing
- Audit log — append-only log entries at each pipeline stage
- Retention policy — scheduled cleanup job for stored contracts/reports

**PERMANENTLY CUT** (Never build, never spec, in any phase):
- ISO 27001 or any compliance-certification claim
- A third "Enterprise Secure" mode beyond Standard / Zero Storage
- Dedicated KMS/Vault key management
- Slack, Notion, or any MCP integration beyond Drive + Gmail
- Any audit log UI, dashboard, or viewer
- "Contract Understanding Agent" or "Legal Classification Agent" as separate nodes
- RBAC / granular permissions / multi-tenant access control

**AMENDMENT (2026-07-14, feature 014) — single-user authentication is now IN scope.**
A **single-user login gate** — email + password (hashed), session cookie — is permitted
to gate the app UI and API. Rationale: the product needs to look and behave like a real,
trustworthy SaaS (owner request), and the reference designs include a landing page and a
login/sign-up screen. This narrowly **reverses feature 011's "no-auth, localhost-only"
decision for the API surface**: all `/api/*` endpoints now require a valid session. It is
explicitly **NOT** multi-tenancy, per-user data scoping, RBAC, or granular permissions —
those remain PERMANENTLY CUT above. There is one shared data space behind a single account;
the login is an *access gate*, not a data-partitioning mechanism. Real Google/Microsoft
SSO is out of scope for now (the buttons render but are disabled). If true multi-tenancy is
ever wanted, it requires a further, separate amendment.

**AMENDMENT (2026-07-15, feature 019) — per-user data isolation is now IN scope.**
This narrows the "multi-tenant access control" item in PERMANENTLY CUT and reverses feature
014's "one shared data space / NOT per-user data scoping" stance (014 D4/AC-10). Each
authenticated account now **privately owns the contracts it uploads**: every data read
(`/api/jobs`, `/api/dashboard`, `/api/jobs/{id}` and its `report`/`events`) is **scoped to the
owning account**, and a job is stamped with its creator's `user_id` at upload. What remains
**permanently cut**: RBAC, roles, permission grants, teams/orgs, cross-account sharing or
collaboration, and any tenant-admin surface — there is **no cross-account visibility and no
access-control matrix**; every account is a flat, single-owner, private workspace. This adds
no LangGraph node/edge and no `ContractState` field. Legacy rows created before this feature
(no owner) are hidden from all accounts, not migrated. Open signup is re-enabled
(`AUTH_SIGNUP_OPEN=True`) because isolation removes the shared-data exposure that justified
closing it.

## 3. Configurable Thresholds Rule

CRAG confidence thresholds (e.g. the 0.73 cutoff) and Self-RAG pass/fail criteria must always be defined as named, configurable constants in a single shared config module — never hardcoded inline in node logic — since these will be tuned against real sample contracts after implementation.

## 4. State Typing Convention

The LangGraph internal state schema uses TypedDict (lightweight, standard LangGraph convention, no runtime validation overhead). All API request/response models and any data crossing a system boundary (HTTP, MCP, file I/O, database) use Pydantic for runtime validation. These two are never mixed within the internal graph state.

## 5. Partial-Update Rule

Every node function returns only the state keys it actually updates (a partial dict), never the full state object, to avoid race conditions and redundant writes.

## 6. State Minimality Rule

Large content (raw document text, full PDFs) is stored as a reference (file path or ID) rather than embedded directly in graph state, since LangGraph checkpoints state after every step.

## 7. Testing Philosophy

TDD where practical: tests are written and confirmed failing before implementation begins; if a test fails after implementation, the implementation is fixed, the test is not weakened or modified to force a pass.

## 8. Model-Separation Rule

The generative LLM (Qwen3 480B via Ollama, used for planning, architecture, and spec/plan creation) and the implementation model (Qwen3 30B, run locally via Ollama through Claude Code) are two distinct model sessions with no shared memory between them. All context that needs to cross from planning to implementation MUST be captured in spec.md, plan.md, and tasks.md — never assumed to carry over conversationally. tasks.md in particular must be written explicitly enough for a smaller, less capable model to implement correctly without needing to fill in ambiguous gaps through inference. Separately, the embedding model (BGE-M3 or Qwen3-Embedding, also via Ollama) is always a distinct concern from either generative model and never substituted for one.

## 9. Local-Model Latency Note

Qwen models served via Ollama (cloud or local) have materially different latency and batching characteristics than a fast hosted API. Any design involving retries, timeouts, or progress streaming must account for this explicitly rather than assuming sub-second response times.

## 10. Spec-First Change Rule

If implementation work reveals that 001-contract-state-schema.md needs to change, the spec file is updated FIRST, with a written rationale, before any corresponding code change is made. Note explicitly that the Phase 2 PrivacyAgent addition is a KNOWN, INTENTIONAL future trigger for this exact rule — that future breaking change is expected, not a failure of Phase 1 planning.

## 11. Git Branching Workflow

Applies to every feature, backend and frontend alike:
- One branch per feature, named feature/0XX-feature-name, where 0XX matches that feature's specs/ folder number exactly.
- A feature branch may only be opened once that feature's spec.md AND plan.md are approved and its tasks.md exists.
- Before implementation starts: checkout main, pull latest, then branch off from there.
- Before merging a feature branch back into main: pull main again, then rebase (or merge main into) the feature branch FIRST and resolve any conflicts there — conflicts are never resolved directly on main.
- A feature branch only merges into main once its tests (per that feature's tasks.md) are passing.
- After a clean merge into main, the feature branch is deleted.
- Every plan.md includes a single line pointing back to this section and stating its own branch name — plan.md files must NOT restate these rules, so the workflow only ever needs to be updated in this one place.
- Note: the .claude/commands/git-start.md and git-finish.md slash commands implement this workflow mechanically — refer to them when starting or finishing a feature branch rather than running the steps manually.