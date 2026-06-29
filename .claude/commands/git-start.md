---
description: Start a new feature branch following the project's git workflow
---

I'm starting work on a feature. Feature spec folder: $ARGUMENTS
(e.g. "005-crag-retrieval")

Follow the git branching workflow defined in specs/000-constitution.md
exactly. Before running anything, confirm:
1. That specs/$ARGUMENTS/spec.md exists
2. That specs/$ARGUMENTS/plan.md exists
3. That specs/$ARGUMENTS/tasks.md exists
4. That I have told you these are approved

If any of those are missing or unapproved, STOP and tell me — do not
create the branch.

If all checks pass, run:
1. git checkout main
2. git pull origin main
3. git checkout -b feature/$ARGUMENTS

Confirm the branch was created and report the current git status.