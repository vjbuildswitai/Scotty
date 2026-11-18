# Beamer fork — LAN file transfer (VJ)

Read `HANDOFF.md` (full context) and `FILES.md` (the design) before touching code.

## What this repo is
A fork of https://github.com/kalkman-code/beamer (free, GPL-3.0 software KVM: one keyboard and
mouse across machines on the same network, clipboard text + images follow the pointer).
Upstream is at `v1.5.21` (commit `e918475`, 2026-11-16). This fork adds **sending files and
folders between two Windows 11 PCs**: copy in Explorer on one PC, cross to the other, Ctrl+V.

The app is called **Scotty** (renaming the exe and UI from Beamer is still to do).
Branch: `file-transfer`. Remote `upstream` = kalkman-code/beamer. Remote `origin` =
https://github.com/vjbuildswitai/Scotty (VJ's fork). Working copy: `D:\Projects\Beamer`.

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
- Tests: `cd win_app && python -m unittest discover -s tests -v` and
  `cd core && python -m unittest discover -s tests -v` must stay green.

## Run / build on Windows
```powershell
cd win_app
.\build_portable.ps1          # makes .venv, installs requirements-win.txt, builds dist\portable\Beamer-portable\Beamer.exe
```
Dev loop: `python -m venv .venv; .venv\Scripts\pip install -r requirements-win.txt` then
`.venv\Scripts\python kvm_bridge_win.py`. Install for real with `.\Install-Beamer.ps1`
(adds firewall rules; add TCP 24822 for the file channel when it exists).

## Work plan (steps 1-4 done 2026-11-19; step 5 built, two-laptop test pending)
1. `core/protocol.py`: `MSG_FILES`, `files_msg()`, `read_files()` validator, `clipboard_files` cap; gate in `core/link.py`.
2. `win_app/clipboard_win.py`: `get_files()` (CF_HDROP via shell32 `DragQueryFileW`), `set_files(paths)` (DROPFILES block, fWide=1).
3. `core/filechannel.py`: sender listener + receiver puller, ticket auth, NaCl SecretBox 1 MiB chunks, SHA-256 per file, `.part` then rename, cancel, progress callbacks; loopback e2e test.
4. `win_app/kvm_bridge_win.py`: on the taking `focus`, if CF_HDROP present and peer has the cap, send the manifest and serve; receiver pulls to the drop folder, sets CF_HDROP, shows a toast with progress/cancel. Settings UI on the Overview page.
5. Build the portable exe, copy to the second laptop, pair, test with a 1 GB file; pointer must stay smooth during the transfer.
