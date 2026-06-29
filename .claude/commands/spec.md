---
description: Generate a spec.md for a ContractSentinel feature, following the project's spec-driven workflow
---

You are generating ONLY a spec.md file for the feature described below. Do
not write plan.md, tasks.md, or any implementation code in this invocation.

Feature to spec: $ARGUMENTS

Before writing anything:
1. Read specs/000-constitution.md and follow every rule in it, especially
   the fixed architecture / node boundaries, the PHASE 2 and PERMANENTLY
   CUT lists, and the spec-driven workflow rule itself.
2. Read specs/001-contract-state-schema.md so this spec's inputs/outputs
   are consistent with the shared state shape already defined there.
3. If a specs/002-tech-stack.md or specs/002-api-contract.md exists, read
   those too for consistency.
4. Check whether this feature appears anywhere in the PHASE 2 or
   PERMANENTLY CUT lists in 000-constitution.md. If it does, STOP and tell
   me explicitly rather than writing the spec.

Create specs/0XX-feature-name/spec.md (use the next available number in
the specs/ folder, matching the existing naming convention) with these
sections, in this order:

- Problem statement: what this feature does and why it exists in the
  pipeline, referencing its place in the fixed architecture from 000.
- Inputs and outputs: exact schema, referencing the relevant slice of
  ContractState from 001-contract-state-schema.md — do not invent new
  field names that conflict with what 001 already defines.
- Acceptance criteria: specific, testable conditions, written so each one
  could become a test case directly.
- Edge cases: explicitly list failure modes, empty inputs, retry
  exhaustion, timeout behavior, and anything specific to this node's
  position in the pipeline.
- Out of scope: what this feature explicitly does NOT handle, pointing to
  which other spec (existing or future) owns that instead.
- Open questions: anything genuinely uncertain that needs my decision
  before this spec is final. Do not silently guess on anything
  architecturally significant.

If this feature involves confidence scoring or retry-validated findings
(CRAG retrieval or Self-RAG validation), also add an "Evaluation" section
describing what metrics should be logged for later analysis (confidence
score distribution, retrieval-path hit rate, retry success rate, false-
flag rate, etc).

When done, tell me the file path you created and list every item in its
"Open questions" section.