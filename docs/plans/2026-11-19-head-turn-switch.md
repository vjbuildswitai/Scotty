# Plan: Switch PCs by turning your head

- Track: scotty-head-turn
- Status: approved
- Approved by VJ: 2026-11-19 (chat)
- Branch: feat/scotty-1.1   PR: -

## Goal
Turn your head to the other laptop's screen and the keyboard and pointer go there; turn back and
they come back. A setting on Overview, off by default. Moving the mouse across the edge still
works as now.

## How it works
- The webcam on the PC that has the keyboard and mouse (the one sending input) watches your face.
  Nothing else does: the other PC's camera stays off.
- Face detection: OpenCV's built-in YuNet detector (`cv2.FaceDetectorYN`, MIT-licensed model of
  about 230 KB shipped with Scotty). It returns eyes, nose and mouth corners. Head turn is read as
  where the nose sits between the eyes (left/right), which is all a two-screen choice needs; no
  eye tracking, no cloud, no extra model download.
- Calibration (30 seconds, once): "Look at this screen" (2 s sample), "Look at <other PC>" (2 s
  sample). With three or more machines, one sample per screen. Stored as numbers in
  `scotty.json`; no picture is ever saved.
- Switching: the head reading must sit past the midpoint between two calibrated screens, by a
  margin, for a dwell time (default 0.4 s), with a cooldown after a switch (default 1 s). Then
  Scotty does exactly what the jump shortcut does: `sender.go(peer)`, or
  `sender.set_redirecting(False)` to come home.
- Never steals typing: no switch while a key or mouse button is held, within 0.8 s of the last
  key press, or during a drag. A glance down at the keyboard is ignored (no face or face too low
  holds the current machine).
- Pause: tray menu "Pause head turn", and a shortcut. Camera light is on while it runs; Scotty's
  tray icon shows a small eye.

## Privacy and security
- Frames live in memory for one detection (~15 fps, 320 px wide) and are dropped. Nothing is
  written, logged or sent; only the switch decision reaches the link (as the normal focus message).
- Runs only while: the setting is on, this PC is paired and sending, and Windows camera access for
  desktop apps is allowed. If Windows blocks the camera, the setting says so with a button that
  opens Settings > Privacy > Camera.
- No new network traffic and no new wire message: the other PC cannot tell a head turn from a
  shortcut press, so stock Beamer peers work unchanged.

## Files that change
- `core/headturn.py` - new, pure Python: calibration maths, smoothing, dwell, cooldown, typing
  guard, decision "stay / go to peer X". No camera, no Qt, fully unit-tested on any OS.
- `win_app/headturn_win.py` - new: camera thread (OpenCV `VideoCapture`, DirectShow/MSMF), YuNet
  per frame -> one number into `core/headturn.py`; start/stop; camera-blocked detection.
- `win_app/assets/face_detection_yunet_2023mar.onnx` + licence note in `THIRD-PARTY-NOTICES`.
- `win_app/app_config.py` - `headturn` block in `scotty.json`: enabled (false), calibration,
  dwell_ms, cooldown_ms, camera index.
- `win_app/kvm_bridge_win.py` - Overview "Head turn" card: switch, Calibrate (a guided overlay on
  each screen saying "look here"), sensitivity slider, camera picker, live "now looking at" dot
  while the settings window is open. Tray: pause/resume.
- `win_app/sender.py` - one entry point `look_at(peer_or_none)` that applies the typing guard and
  calls `go`/`set_redirecting`.
- `win_app/requirements-win.txt` - `opencv-python-headless` (Apache-2.0). Adds roughly 40-60 MB
  to the download; it is loaded only when the setting is turned on.
- `locales/it.po`, `SECURITY.md` (camera section), `README.md`, `TESTING.md`.

## Order of work
1. `core/headturn.py` + tests (synthetic head-turn traces: steady, glance, typing, look down,
   jitter, three screens).
2. Camera + YuNet wrapper; a debug command that prints the head reading, run on the LOQ.
3. Sender entry point + typing guard tests.
4. Settings card, calibration overlay, tray pause, i18n.
5. Two-laptop trial: 20 deliberate turns, 5 minutes of typing with glances; count wrong switches.

## Tests that prove it
- New: `core/tests/test_headturn.py` (decision logic), `win_app/tests/test_headturn_win.py`
  (thread start/stop without a camera, blocked-camera message, setting off = camera never opened),
  `win_app/tests/test_sender_look_at.py` (typing guard).
- Existing: `bash scripts/verify.sh` green.
- Manual: the two-laptop trial above; acceptance = no wrong switch while typing, a deliberate turn
  switches in under 1 s.

## Risks
- Lighting: dim rooms or strong backlight lose the face. Mitigation: "no face" holds the current
  machine; the card shows "can't see you" so it is never a mystery.
- Laptop side by side at a small angle: head turn may be small. Calibration measures it and the
  card warns when the two screens are too close to tell apart.
- CPU: YuNet at 320 px is a few percent of one core; measured on the LOQ before release.
- Download size grows; acceptable for an optional feature, revisit if it matters.

## Rollback
- Setting off (default) never opens the camera or imports OpenCV. Revert the PR to remove it.

## Deviations
-
