# Review policy (used by the Claude PR review)

Review every PR in three passes. Rank findings Important or Nit.

## 1. Bugs
Logic errors, broken edge cases, regressions in code that calls the changed code, wrong error handling, race conditions, anything that fails on real data rather than the test fixture.

## 2. Security
Secrets or keys in code, injection (SQL, shell, prompt), missing auth on an endpoint, customer or lead data (emails, phone numbers, ad account IDs) in logs or error messages, unsafe file handling of uploads.

## 3. Plan and rules
- The diff matches the plan linked in the PR (`docs/plans/...`). Changes outside the plan are flagged unless the plan's Deviations section explains them.
- The rules in `CLAUDE.md` hold (conventions, "Never" list).
- A bug fix comes with a test that fails without the fix.
- Money and paid calls: any new call to a paid API (Claude, OpenAI, Higgsfield, Google Ads, DataForSEO...) must be behind an explicit cap or an approval, never in a loop without a limit.

## Severity
- **Important** = breaks behaviour, leaks data, spends money unexpectedly, or breaks a CLAUDE.md rule. Must be fixed before merge.
- **Nit** = style or naming. Max five per review; summarise the rest as a count.

## Skip
Generated files, lock files, vendored code, `docs/plans/`, anything CI already enforces (formatting, the guard checks).

## Output
Inline comments on the lines concerned. If there are no Important findings, one short summary comment saying so. Never approve the PR; VJ merges.
