# Handoff — two-laptop ecosystem + Beamer fork (2026-11-18)

Everything decided and found so far, so this project can continue on VJ's PC without the chat.

## The goal
Two Windows 11 laptops (Lenovo LOQ `VIJAYARAJ-DEV`, model 83DV, Windows 11 Home 25H2; a second
Windows 11 laptop) and a CMF Phone by Nothing, working as one setup: one Bluetooth keyboard and one
Bluetooth mouse across both laptops, copy-paste between them, moving and opening files across them.

## Decisions VJ made
- Fork Beamer and add file sending over the local network (instead of Microsoft PowerToys Mouse
  Without Borders, which already does clipboard + single file ≤100 MB). He expects Beamer to work better.
- Fork under his own GitHub account for now. The GitHub account connected to Claude is
  `BigBoost-Dev`; forking from the Claude side was blocked by the proxy (write to `/forks` not
  permitted), so the fork is created by hand at https://github.com/kalkman-code/beamer/fork.
- File-size cap: 2 GB default, must be configurable upward.
- Drop folder (where received files land before Ctrl+V): default `%USERPROFILE%\Downloads\Beamer Drop`,
  changeable in settings.

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

## Status
- Branch `file-transfer` created from `v1.5.21`; `FILES.md`, `CLAUDE.md`, `HANDOFF.md` added.
  No feature code written yet.
- Task list: (1) fork + attach, (2) protocol, (3) clipboard CF_HDROP, (4) side channel,
  (5) app wiring + settings + toast, (6) build portable exe on the LOQ and test on both laptops.

## Continue from the PC
```powershell
cd C:\Users\Vijayaraj-Dev\Projects\beamer
git status                       # the three .md files are uncommitted on branch file-transfer
git remote add origin https://github.com/<your-account>/beamer.git
git push -u origin file-transfer
cd win_app; .\build_portable.ps1 # proves the stock app builds here before changing anything
```
Then open the folder in Claude Code; `CLAUDE.md` carries the rules and the work plan.
