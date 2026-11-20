# Plan: Your Android phone as another screen

- Track: scotty-phone
- Status: draft (scope agreed in chat 2026-11-19; build after the UI work and the Beamer fixes)
- Approved by VJ: -
- Branch: feat/scotty-phone   PR: -

## Goal
The phone shows in a window on the PC with the keyboard and mouse. Move the pointer into it and
use the phone with your mouse and keyboard: reply in the phone's own WhatsApp, test a website on
a real phone, take a screenshot that lands on the PC. No app to install on the phone.

## How it works
- Scotty bundles scrcpy (Apache-2.0, compatible with GPL-3.0) and Google's adb. scrcpy mirrors the
  phone's screen and sends mouse and keyboard to it over Wi-Fi; it needs only Android's
  **Wireless debugging** turned on once (Android 11 and later).
- **Pairing, once:** Scotty's setup guide walks through Developer options, Wireless debugging,
  "Pair device with pairing code"; Scotty finds the phone on the network and asks for the 6-digit
  code (`adb pair`). After that, Scotty connects on its own when the phone is on the same Wi-Fi.
- **Phone window:** Scotty starts scrcpy with the phone's name as the title, remembers where the
  window sat, and offers "Phone" on Home and in the tray.
- **Screenshot button:** full-resolution screenshot from the phone (`adb exec-out screencap`)
  to the clipboard and to `Pictures\Scotty Phone` with the date; one click, no cable.
- **Open this page on the phone:** paste or send a URL (tray, or a hotkey that reads the
  clipboard) and the phone opens it in its browser (`am start VIEW`). For website testing:
  copy the URL on the PC, press the key, look at the phone window, screenshot.
- **Files:** drag files onto the phone window to copy them to the phone's Downloads (scrcpy does
  this); phone to PC through the screenshot folder for now.

## Security
- Wireless debugging lets the paired PC control the phone completely. Scotty pairs only the PC
  it runs on, shows a clear "Phone connected" state, and has a **Disconnect phone** button that
  also turns off the adb connection. The setup guide says this in one line and recommends turning
  Wireless debugging off when not needed.
- Nothing leaves your network; no Google account or cloud involved.

## Files that change
- `win_app/phone_win.py` (new): find adb/scrcpy, pair, connect, start/stop the window, screenshot,
  open URL. `core/phone.py` (new, pure): adb output parsing, device list, URL validation; tested.
- `win_app/build*.spec`, `build_portable.ps1`: bundle scrcpy + adb (about 10 MB, to be measured);
  licences in THIRD-PARTY-NOTICES.
- Setup guide step "Add your phone (optional)", Home card "Phone", tray items; Italian strings.
- `SECURITY.md` (Phone section), `README.md`, `TESTING.md`.

## Order of work
1. Pure parsing and URL rules + tests. 2. adb pair/connect on VJ's phone from a debug command.
3. Window, screenshot, open URL. 4. Guide step, Home card, tray. 5. Trial: reply to a WhatsApp
message and screenshot a mobile site, timed.

## Risks
- Some phones (Xiaomi, some Samsung) need an extra "USB debugging (Security settings)" switch for
  keyboard and mouse; the guide names it.
- Wireless debugging turns itself off after a reboot on some phones; Scotty says "turn it on again"
  rather than failing silently.
- Banking and some secure apps show a black window when mirrored (Android's rule, not ours).

## Rollback
- Optional feature, off until paired; revert the PR to remove it.
