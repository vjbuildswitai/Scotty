# Handoff — Scotty (two-laptop setup, built on Beamer), updated 2026-11-19

Everything decided and found so far, so this project can continue on VJ's PC without the chat.

## The goal
Two Windows 11 laptops (Lenovo LOQ `VIJAYARAJ-DEV`, model 83DV, Windows 11 Home 25H2; a second
Windows 11 laptop) and a CMF Phone by Nothing, working as one setup: one Bluetooth keyboard and one
Bluetooth mouse across both laptops, copy-paste between them, moving and opening files across them.

## Decisions VJ made
- Fork Beamer and add file sending over the local network (instead of Microsoft PowerToys Mouse
  Without Borders, which already does clipboard + single file ≤100 MB). He expects Beamer to work better.
- The product is **Scotty** (free forever, open source, shown on his channel), built on Beamer
  and crediting it. Repo: https://github.com/vjbuildswitai/Scotty; `main` is what people download.
- File-size cap: 2 GB default, must be configurable upward.
- Drop folder: `%USERPROFILE%\Downloads\Scotty Drop`, changeable. Pasting moves files out of it
  (one copy, not two); what is never pasted is cleared after 7 days.
- Security must be top class: assume people will look for holes (SECURITY.md, Files).
- Work follows his SDLC kit: plan, OK, branch, PR, verify, release only on his OK.
- One working copy only: `D:\Projects\Beamer` on the LOQ.

## What was verified about the tools (Nov 2026)
- Beamer 1.5.21 (GPL-3.0, one maintainer, Python/PySide6/PyNaCl, PyInstaller builds). Two Windows
  PCs supported. Pairs with a six-digit code on the same LAN (UDP 24821 discovery, TCP 24821
  pairing, TCP 24820 input). Clipboard carries text ≤256 KiB and PNG ≤8 MiB on the input link.
  **Files do not cross** — that is the gap this fork fills. Admin windows/UAC and the lock screen
  need local input unless the optional secure-desktop service is enabled.
- PowerToys Mouse Without Borders (Microsoft, free): keyboard/mouse across up to 4 PCs, clipboard,
  copy/drag of one file ≤100 MB, no folders. Hotfix v0.102.3101.0 (Nov 6, 2026) fixed pairing.
- Phone Link cross-device copy/paste is NOT available on Nothing/CMF phones (Microsoft lists
  Surface Duo, Samsung, HONOR, OPPO/OnePlus/Realme, ASUS, vivo, Xiaomi only). Phone Link still
  gives SMS, notifications, calls, photos and File Explorer browsing. Use Quick Share for Windows
  (Google) on both laptops for phone↔PC files; Quick Share is not for PC↔PC.
- Big video files: a shared folder (SMB) over 5 GHz Wi‑Fi or an Ethernet cable; nothing above
  replaces that.

## State of the LOQ when checked (2026-11-18, via Desktop Commander)
- PowerToys not installed. Clipboard history off.
- Wi‑Fi `KraftPanda` was on the **Public** network profile — must be **Private** on both laptops
  or Beamer/MWB/shares cannot connect. Link speed 144 Mbps (≈10 MB/s real transfers); use 5 GHz
  or a Cat6 cable between the laptops for multi-GB moves.
- Only "Noise Buds N1 Pro" was connected over Bluetooth at the time.

## The design (see FILES.md)
Manifest on the input link + separate encrypted pull channel on TCP 24822; CF_HDROP in/out on
Windows; `.part` writes renamed on completion; cap and drop folder in settings; capability-gated so
stock Beamer/Mac peers are unaffected.

## Status (2026-11-19, morning)
- Branch `feat/scotty-1.0` on GitHub holds all of Scotty 1.0: files across the edge, the name,
  icon and identity, update checks from this repo, the security fixes in
  `docs/plans/2026-11-19-security-and-drop-folder.md`, move-on-paste and cleanup, sending progress
  and Cancel, stronger portable passphrase, the SDLC kit (guards, verify, CI, AI review), README,
  SECURITY (Files), TESTING, CHANGELOG. It reaches `main` by PR.
- Proof: `bash scripts/verify.sh` (all tests against `.sdlc/known-failures.txt`, plus 1 GB through
  the file channel).
- Not done: the two-laptop test in TESTING.md (needs VJ and both PCs); a published release (needs
  his OK; the build zip is `win_app\dist\portable\Scotty-Portable-1.0.0-windows-x64.zip`).
- VJ, once: install the Claude GitHub app on the repo and set `CLAUDE_CODE_OAUTH_TOKEN` (kit
  README) so PRs get the AI review; turn on private vulnerability reporting in the repo's
  Settings, Security.

## Test on both laptops
Follow TESTING.md. Wi-Fi `KraftPanda` must be **Private** on both. Connect the keyboard and mouse
to one laptop only; Scotty carries them to the other over the network.

## Idea, not planned: switch by where you look
VJ saw a two-Mac setup where keyboard and mouse follow the screen he looks at. It exists as small
open-source tools (gazectl, miru, EyeFocus) that read head direction from a webcam after a short
calibration and move focus between monitors. For Scotty it would be: the laptop the keyboard is
connected to watches its webcam, and turning your head towards the other laptop does what Beamer's
jump key already does (hand input over). Trade-offs: webcam always on (privacy, its light stays
on), lighting and glasses affect it, false switches when you glance away, and CPU use. Would need
its own plan, an off-by-default setting and on-device processing only.
