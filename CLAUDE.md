# Scotty (VJ)

Read `HANDOFF.md` (full context), `FILES.md` (the design) and `SECURITY.md` (Files) before touching code.

## What this repo is
**Scotty**: one keyboard and mouse across Windows PCs, and copied files that follow the pointer
(copy in Explorer on one PC, cross to the other, Ctrl+V). Built on Beamer
(https://github.com/kalkman-code/beamer, GPL-3.0) at `v1.5.21` (commit `e918475`). Scotty is the
product people download; Beamer is only ever named as what it is based on.

Working copy: `D:\Projects\Beamer` on VJ's laptop, the only one. Remote `origin` =
https://github.com/vjbuildswitai/Scotty, `upstream` = kalkman-code/beamer. `main` is what people
download; work happens on `feat/...` branches and reaches `main` by PR.

## Where things are
- Files: `core/filechannel.py` (encrypted channel, staging, cleanup, mark of the web),
  `win_app/scotty_files.py` (bridge between clipboard, channel and app), `win_app/scotty_toast.py`
  (progress panel), `win_app/clipboard_win.py` (CF_HDROP, move effect), hooks in `core/receiver.py`,
  `win_app/sender.py`, `core/owner.py`.
- Name and version: `core/brand.py` (Scotty 1.0.0; upstream strings are shown as Scotty except
  where they mean upstream Beamer). Wire version stays upstream's `VERSION`.
- Tests and baseline: `tools/run_suite.py`, `.sdlc/known-failures.txt` (only shrinks).

## Rules for this fork
- Additive only. Stock Beamer and the Mac app must keep working unchanged: every new message is
  gated on a new `clipboard_files` capability in `hello`/`welcome` (see `core/link.py` `_caps`).
- File bytes never travel on the input link (`core/link.py`). They use their own TCP connection
  (port 24822) so the pointer never stalls. Only the small `files` manifest rides the link.
- Keep upstream's style: ctypes (no pywin32-only paths in new code), guarded imports so modules
  load off Windows, pure-Python encode/decode that `unittest` can cover on Linux/macOS.
- Settings code lives in `win_app/app_config.py` (`load_files_settings`/`save_files_settings`),
  stored in `scotty.json` beside `settings.json`; defaults: enabled, drop folder
  `%USERPROFILE%\Downloads\Scotty Drop`, max 2 GiB (raisable to any size on Overview → Files).
- Do not change `WIRE.md` semantics for existing messages. Document the new message and
  capability in `WIRE.md` under a new "Files" section.
- Security is a feature: any change to the file channel keeps every property in SECURITY.md
  (Files) and adds a test for it; anything received from the other PC is untrusted input.
- Never change what upstream's wire or pairing says (version, names), so stock Beamer peers work.
- User-visible text goes through `tr()` with an Italian entry in `locales/it.po`
  (`python tools/i18n_extract.py`, then `--check`).
- Done = `bash scripts/verify.sh` passes (Git Bash on Windows; about 10 minutes).

## Run / build on Windows
```powershell
cd win_app
.\build_portable.ps1          # dist\portable\Scotty-Portable-<version>-windows-x64.zip
```
Dev loop: `win_app\.venv\Scripts\python kvm_bridge_win.py --config <a temp folder>\settings.json`
(a throwaway settings folder keeps the real profile clean). Install for real with
`.\Install-Scotty.ps1` (firewall rules for 24820, 24821, 24822, Private only).

## Still open
- Two-laptop test (TESTING.md) needs VJ and both PCs.
- Idea, not planned: switch PCs by where you look (webcam head pose), see HANDOFF.md.

<!-- sdlc-kit:start -->
## How we build (SDLC) - applies to every change
1. **Plan first.** Anything bigger than a one-line fix gets `docs/plans/YYYY-MM-DD-<slug>.md` from `docs/plans/_TEMPLATE.md` (files, order, tests, risks, rollback). Write it from a read-only look at the code; VJ approves it before code is edited. If the build departs from the plan, update the plan in the same commit.
2. **Branch + PR.** Work on `feat/<slug>` or `fix/<slug>`, open a PR into `main`. Never commit to a protected branch: `main`, `file-transfer`.
3. **Bug fixes are test-first.** Write a test that fails because of the bug, commit it, add its path to `.sdlc/test-lock`, then fix the code without touching the test. Remove the lock line once the fix is merged.
4. **Done = verified.** Run `bash scripts/verify.sh` and paste the last lines of its output. No output, not done.
5. **Releases need VJ.** Deploys and pushes to protected branches need his OK in the chat; the guards block them otherwise. After his OK, run that one command with `SDLC_RELEASE_OK=1`.
6. **Every PR gets a Claude review** against `REVIEW.md`. Fix Important findings before asking VJ to merge. A finding that repeats becomes a rule in this file.
7. **Paid calls** (Claude, OpenAI, Higgsfield, ad platforms...) never run in tests or loops without a cap and VJ's OK.

Guards: `.sdlc/guard.js` with `.sdlc/config.json` (protected branches, deploy patterns, secret paths). They run as Claude Code hooks, git hooks and a CI check. New clone: `node .sdlc/guard.js install`.
<!-- sdlc-kit:end -->
