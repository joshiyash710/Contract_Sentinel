---
description: Run tests for a specific feature and report against its tasks.md acceptance criteria
---

Run the test suite for this feature: $ARGUMENTS (e.g. "005-crag-retrieval")

1. Read specs/$ARGUMENTS/tasks.md to know what tests should exist for
   this feature and what they're supposed to verify.
2. Locate and run the corresponding tests under backend/tests/unit/ and
   backend/tests/integration/ (run only tests relevant to this feature,
   not the full suite, unless I ask for the full suite).
3. Per the constitution's testing philosophy: if a test fails, the
   implementation is what gets fixed — do not weaken or modify the test
   to force a pass. If you believe a test itself is wrong (not the
   implementation), STOP and tell me explicitly why, rather than editing
   the test unilaterally.
4. Report: which tests passed, which failed, and for any failure, your
   diagnosis of whether the bug is in the implementation or whether the
   spec/acceptance criteria itself may need revisiting (flag this
   separately — don't conflate "test failed" with "spec might be wrong").
5. If this feature involves confidence scoring or retry-validated
   findings (CRAG retrieval or Self-RAG validation), additionally run the
   corresponding script under backend/eval/ and report the metrics
   (confidence distribution, retry success rate, etc.) — do not just
   report pass/fail for these, since the eval numbers matter more than a
   binary test result here.