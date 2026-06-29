---
description: Finish a feature branch — rebase, merge to main, clean up, following the project's git workflow
---

I've finished implementing a feature and want to merge it back to main.
Feature branch: $ARGUMENTS (e.g. "005-crag-retrieval")

Follow the git branching workflow in specs/000-constitution.md exactly.

Before merging, confirm:
1. All tests defined in specs/$ARGUMENTS/tasks.md are passing — run the
   test suite and show me the result first
2. If this feature involves confidence scoring or retry-validated
   findings (CRAG retrieval or Self-RAG validation), also confirm at
   least one eval script has been run with sane output

If tests are not passing, STOP and tell me what's failing — do not merge.

If all checks pass, run in this exact order:
1. git checkout main
2. git pull origin main
3. git checkout feature/$ARGUMENTS
4. git rebase main          (resolve any conflicts here, on this branch —
                              never on main; if conflicts arise, stop and
                              show me what needs resolving rather than
                              guessing at a resolution)
5. git checkout main
6. git merge feature/$ARGUMENTS
7. git push origin main
8. git branch -d feature/$ARGUMENTS

Confirm each step succeeded and report final git status.