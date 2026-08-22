## What this changes

## Why

## Day / scope
Which day's scope (Section 3 of the build plan) does this belong to?

## Checklist
- [ ] `ruff check` / `black --check` pass (backend) — or CI will catch it
- [ ] `eslint` / `prettier --check` pass (frontend) — or CI will catch it
- [ ] Tests added or updated for the behavior changed
- [ ] No secrets in the diff (`.env` never committed)
- [ ] If this changes a stack/architecture decision, ADR.md was updated
- [ ] If this touches a deploy-triggering path, the reviewer subagent gate
      (REVIEW.md) was run before merge
