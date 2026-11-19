# Plan: security hardening, the drop folder, and the SDLC kit (2026-11-19)

Branch: `feat/scotty-rename` (already holds the rename, brand, update-check and WIP progress commits).
Status: done (approved by VJ in chat; merged to main in PR #1, 2026-11-19).

## 1. Apply the SDLC kit first
- `node D:/Projects/sdlc-kit/apply.js --repo D:/Projects/Beamer --base file-transfer --protected file-transfer,main --verify "bash scripts/verify.sh"`.
- `scripts/verify.sh`: the core and win_app test suites, the translation check, and the 1 GB loopback
  transfer. Known upstream failures (4 core tests needing commits missing from GitHub) go in a
  baseline that can only shrink.
- From then on: guards on, one PR per change into `file-transfer`, CI with the AI review, VJ merges.
- VJ, once: install the Claude GitHub app on vjbuildswitai/Scotty, `claude setup-token`,
  `gh secret set CLAUDE_CODE_OAUTH_TOKEN -R vjbuildswitai/Scotty`.

## 2. The drop folder: one copy, not two
Why it exists: Windows can only paste files that already exist on this PC, so they have to land
somewhere first. Today that leaves a second copy behind in the drop folder every time.

Fix:
- **Paste moves instead of copies.** Received files go on the clipboard marked "move" (the same
  mark Explorer's Cut uses). Ctrl+V moves them out of the drop folder into the destination. On the
  same drive that is an instant rename, no second copy; on another drive Windows copies then deletes.
  The drop folder empties itself as you paste.
- **Leftovers clear themselves.** Anything not pasted is deleted after 7 days (setting: 1 to 365
  days, or never). Only Scotty's own dated folders inside the drop folder are touched, never any
  other file there.
- **Offer is single-use.** Once the other PC has fetched everything, the sender withdraws the offer.
- Considered and not chosen now: "virtual files" (Explorer streams straight from the network at paste
  time, no drop folder at all). Paste would then wait on the network with no progress or cancel, and
  it needs a COM data object written from scratch. Can be a later step.

## 3. Security: what holds, and what gets fixed
Holds today (checked):
- File bytes and the listing are encrypted and authenticated (NaCl SecretBox) with keys derived by
  HKDF-SHA256 from a 256-bit one-time ticket plus fresh randoms from both ends: a new key per
  connection and per direction, so no nonce is ever reused and a replayed or reordered frame fails.
- The ticket only travels inside Beamer's own encrypted, paired link; it is never on the file
  connection or in any log.
- The receiver cannot be made to write outside the drop folder: every path is checked (no `..`,
  drives, `:` streams, device names, trailing dots or spaces, case-insensitive duplicates).
- The sender serves only the entries it listed, by index; nothing else on the disk is reachable.
- Size, count and free-space limits are checked before anything is fetched; failed or cancelled
  transfers leave nothing. Files are only taken from the PC that drives this one (or was just let go).
- Firewall rules are Private-network only.
- Portable passphrase: Argon2id (interactive strength), 12-character minimum (upstream).

Fixes in this change:
- S1 **Connection flood**: cap simultaneous file connections (8) so a LAN device cannot exhaust
  threads; the 10-second handshake limit stays.
- S2 **Address check by name**: when a peer is configured by host name, resolve it and compare IPs
  (today it fails closed, so transfers are refused); serve IPv6 too (dual-stack listener).
- S3 **Mark of the Web**: received files get the Windows "came from another computer" mark, so
  SmartScreen warns before running a received program and Office opens received documents in
  Protected View. Setting to turn it off.
- S4 **Notice text**: the progress panel shows file names as plain text only (a crafted name can no
  longer render as formatted text).
- S5 **Single-use offers** (also above), shrinking the window a ticket is good for.
- S6 Optional, VJ to decide: raise the portable passphrase's Argon2id to "moderate" strength (256 MiB per
  guess, about 4x slower to brute-force a stolen portable folder; unlocking takes about 1 s). Needs a
  versioned vault format so older portable folders still open.
- Out of scope: the security of Beamer's own pairing and input link (upstream's design, unchanged).

Independent check: the PR's AI review (kit CI) plus a separate reviewer pass over core/filechannel.py
and win_app/scotty_files.py with only the threat list above as its brief.

## Acceptance checks (each under a minute for VJ)
1. Copy a file on laptop A, Ctrl+V on laptop B: the file is at the destination and the drop folder
   is empty.
2. Run a downloaded-looking .exe that was sent: Windows shows the "from another computer" warning.
3. `bash scripts/verify.sh` ends with all suites passing (baseline failures listed by name).
4. A file name like `<b>big</b>.txt` shows exactly that in the panel, not bold text.
5. The Files settings show "Clear files not pasted after: 7 days".
