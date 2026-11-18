# Files across the edge — Scotty (fork feature, Windows ↔ Windows)

Goal: copy files or folders in Explorer on one PC, cross to the other PC, press Ctrl+V — the real
files land there. Same local network only. Nothing leaves the LAN.

## Why not the existing clipboard message
`clipboard` rides on the input link (WIRE.md §3, §5). It is capped at 256 KiB of text and an 8 MiB
PNG, and a slow frame on that link stalls mouse and keyboard events behind it. Files therefore get
their own connection and never touch the input link except for a small manifest.

## Pieces
1. **Capability** `clipboard_files` in `hello`/`welcome` (core/protocol.py). A peer without it
   (stock Beamer, the Mac app) never receives a manifest. Fully backward compatible.
2. **Manifest** message `files` on the input link, sent with the clipboard right after the taking
   `focus` when the source clipboard holds `CF_HDROP` paths:
   `{transfer, ticket, port, names, count, total_bytes}` (WIRE.md section 11). It is a summary
   only: the top-level names, how many files and bytes. The full listing comes over the side
   channel, so the manifest stays far under the 64 KiB at which the link treats a frame as large
   and drops it outside a clipboard switch. `ticket` is 32 random bytes that only the paired peer
   sees, because the link is already encrypted. Names are checked so a received file can never
   land outside the drop folder (no `..`, no drive, no Windows device names).
3. **Side channel** (core/filechannel.py): the sender listens on TCP 24822. The receiver connects,
   sends the ticket, receives the full listing (relative paths and sizes), and pulls each entry. The stream is NaCl SecretBox-encrypted with a key derived
   from the ticket, 1 MiB chunks, counter nonces, SHA-256 per file. Pull model: the receiver owns the
   writes and can cancel.
4. **Clipboard** (win_app/clipboard_win.py): read `CF_HDROP` via shell32 `DragQueryFileW`; write it
   back by building a `DROPFILES` block (20-byte header, `fWide=1`, double-NUL UTF-16 list).
5. **Drop folder**: files are written under `<drop>/<yyyy-mm-dd>/…` with `.part` names and renamed
   on completion. When the transfer finishes, the top-level paths go onto the receiver's clipboard
   as `CF_HDROP`, so Ctrl+V in Explorer pastes them. A toast shows progress and a Cancel.
6. **Settings** (win_app/app_config.py + Overview page): `files.enabled` (on), `files.drop_folder`
   (default `%USERPROFILE%\Downloads\Beamer Drop`), `files.max_bytes` (default 2 GiB, any value).
   Over the cap: nothing is sent and the sender shows a toast saying so.
7. **Tests**: protocol validators, DROPFILES encode/decode, chunk framing, and a loopback
   end-to-end transfer that runs on Linux CI.

## Not in v1
Mac/Linux senders or receivers, drag-and-drop across the edge, resume after a dropped link
(the transfer restarts), transfers larger than the cap.
