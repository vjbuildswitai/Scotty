# Plans

One file per change that is bigger than a one-line fix: `YYYY-MM-DD-<slug>.md`, copied from `_TEMPLATE.md`.

- Claude writes the plan first (read-only look at the code), VJ approves it, then code is written.
- The PR links its plan. The Claude review checks the diff against it.
- If the build departs from the plan, the plan is updated in the same commit (Deviations section).
- Why/what for the wider feature lives in the vault track brief (`Brain/<project>/_state/tracks/`). The plan is the how, and it lives here next to the code it describes.
