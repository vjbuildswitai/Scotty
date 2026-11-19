# Plan: <title>

- Track: <vault track slug, e.g. static-audit>
- Status: draft | approved | done
- Approved by VJ: <date, or "-">
- Branch: <feat/... or fix/...>   PR: <#number>

## Goal
What changes for the user, in 2-3 lines (from the track brief).

## Files that change
- `path/to/file` - what changes and why

## Order of work
1. ...

## Tests that prove it
- Existing tests that must still pass: ...
- New tests (for a bug: the failing test written first, then locked in `.sdlc/test-lock`): ...
- Manual check, if any (URL + what to see): ...

## Risks
- What could break, and what else touches this code.

## Rollback
- How to undo if it misbehaves after release (revert commit, previous image tag, feature flag).

## Deviations
Update this section in the same commit if the build departs from the plan.
