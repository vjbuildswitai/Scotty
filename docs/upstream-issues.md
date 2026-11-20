# Beamer's open issues, and what they mean for Scotty (2026-11-19)

Upstream has no commits after v1.5.21 (e918475), the version Scotty is built on, so every open
Beamer issue is also in Scotty unless Scotty's own code changed that path. 42 issues are open
(62 in all). Below: the ones that can touch Scotty's setup (Windows to Windows, one keyboard and
mouse on one PC), what Scotty does about each, and whether it is checked.

"Inherited" means the code is Beamer's and unchanged in Scotty. Mac, Linux, Wayland, translation
and Android requests are left out: Scotty ships for Windows only.

## Bugs that can hit a Windows-to-Windows setup

| # | What | Scotty | Plan |
|---|---|---|---|
| 73 | One laptop on the other's hotspot: only the hotspot host can drive | Inherited | Reproduce on VJ's two laptops (likely: the host's address seen from the client is the hotspot gateway, so the pinned address is wrong). Fix, test, offer upstream |
| 74 | Short network drops send the pointer home at once | Inherited | Add a short grace period before giving input back; test with a simulated drop |
| 64 | Caps Lock and Num Lock get mixed between PCs (Win 11 to Win 10) | Inherited | Reproduce; send lock state with the take, as for modifiers |
| 45 | Switching back within 5 s after the other PC took input is refused | Inherited | Matters more with head turn (quick look back). Reproduce; shorten or drop the refusal when the same person drives both |
| 75 | Cannot click a UAC prompt on the second PC | Inherited; a Windows rule (the secure desktop takes no synthetic input) | Documented. Installed Scotty with the optional secure desktop helper can; portable cannot |
| 67 | Punctuation follows the sending PC's layout when the two layouts differ | Inherited | Only with different layouts on the two PCs. Later |
| 70 | Memory keeps growing after closing (reported on 1.5.1) | Not reproduced on 1.5.21 | Check: close Scotty, watch Task Manager for 10 minutes |
| 46 | Installer shows an "Administrator maintenance" error | Installer only (portable unaffected) | Check when the installer is built for the Store/SignPath work |
| 43 | Scrolling the settings stops on a slider and changes it | Fixed in the code Scotty has | Covered by `test_scroll_wheel_focus` (passes) |

## Requests Scotty answers or should

| # | What | Scotty |
|---|---|---|
| 29 | Copy files on one PC, paste on the other | **Done** (files across the edge, Windows to Windows) |
| 36 | Drag and drop files between PCs | Not yet; copy and paste covers it |
| 76 | Stop crossing while a full-screen game is focused | **Needed for head turn too**: looking down at a game could switch. Add: no head-turn switch while a full-screen app has focus |
| 58 | A key to lock input to the current PC | **Needed for head turn**: a pause key beside the tray item |
| 77 | Put the pointer in the middle of the screen after switching | **Wanted for head turn**: a head-turn switch should land the pointer centred, not at an edge |
| 14 | Use each PC's own keyboard and mouse at the same time | Out of scope |
| 23, 30, 69 | Share audio | Out of scope |
| 25 | Android | Out of scope (TwinDesk does this) |

## So, is Scotty perfect?

No. It carries every Beamer bug above that touches Windows, and its own parts have only been
tested on one PC (loopback) so far. What is solid: the file channel (53 tests, independent security
review, 1 GB verified), head turn's decision logic (16 tests) and its camera thread (14 tests).
What is not yet proven: the two-laptop run, head turn on a real face, and #73, #74, #64, #45 on
VJ's laptops. Order of work: the head-turn guards (#76, #58, #77) with the UI build, then reproduce
and fix #73, #74, #64 and #45 on the two laptops, each test-first, each offered back to Beamer.
