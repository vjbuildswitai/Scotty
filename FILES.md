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
3. **Side channel** (core/filechannel.py): the sender listens on TCP 24822. The receiver connects
   and sends the transfer id and 32 random bytes; the sender answers with its own 32. Each
   direction's key is HKDF-SHA256 over the ticket with both randoms as salt, so the ticket itself
   never crosses this connection and no key is used twice. Frames are NaCl SecretBox with counter
   nonces; file bytes go in 1 MiB frames. The receiver asks for the full listing (relative paths and
   sizes) and then each file; the sender rechecks size and modified time before sending one, and
   SHA-256 is compared per file. Pull model: the receiver owns the writes and can cancel; the
   sender can cancel too. An offer is single-use (gone once everything arrived), lasts at most 10
   minutes, is served only to the resolved address it was offered to, and the listener holds at most
   8 connections at once.
4. **Clipboard** (win_app/clipboard_win.py): `get_files()` / `set_files(paths)` read and write the
   `CF_HDROP` block (20-byte `DROPFILES` header, `fWide=1`, double-NUL UTF-16 list), parsed and built
   in pure Python rather than through `DragQueryFileW`, so it is tested off Windows. Cut (Ctrl+X) is
   treated as copy: nothing is ever deleted on the sending PC.
5. **Drop folder**: files arrive in `<drop>/.scotty-incoming/<transfer>/` (each file as `.part`
   until its hash checks out), and only when everything arrived do the top-level items move to
   `<drop>/<yyyy-mm-dd>/`, renamed "name (2)" if taken. A cancelled or failed transfer leaves
   nothing. Each file gets the mark of the web (`:Zone.Identifier`, ZoneId=3) before it moves into
   place, unless that setting is off. The landed paths go onto the receiver's clipboard as
   `CF_HDROP` with `Preferred DropEffect` = move (what Explorer's Cut writes), so Ctrl+V moves them
   out of the drop folder: one copy at the destination, an instant rename on the same drive. Dated
   folders older than `keep_days` (7) and empty ones from earlier days are removed at start and
   after each transfer; nothing else in the drop folder is touched, and never through a link. A
   small panel in the corner shows progress and Cancel on both PCs, and Open folder at the end.
6. **App** (win_app/scotty_files.py `FilesBridge`, hooks in core/receiver.py, win_app/sender.py,
   core/owner.py): the manifest goes out with the clipboard, both ways. The driven PC takes one only
   from the PC driving it; the driving PC only from a PC it has just let go of, once, by the
   clipboard's rule and window (owner `files_arrived`). A newer manifest cancels an older fetch.
7. **Settings** (Overview page, Files; saved in `scotty.json` beside `settings.json` so profile
   sync and migrations never touch them): on/off (on), drop folder (default
   `%USERPROFILE%\Downloads\Scotty Drop`), largest transfer in GB (default 2, up to 1,000,000),
   days to keep what was not pasted (7; 0 keeps it), mark received files (on).
   Over the cap: nothing is sent and the sender says so. `clipboard_files` is announced only while
   the listener is up; switching files on or off reaches the other PC when the link next connects.
8. **Firewall**: the installer adds `Scotty Files (TCP-In)`, TCP 24822, Private profile, for the exe.
   A portable copy gets Windows' own Allow prompt the first time it listens.
9. **Tests**: protocol validators, CF_HDROP codec and clipboard writes over fakes, loopback
   end-to-end transfers including tampering, expiry and cancel (Linux and Windows), the bridge with
   a real transfer, the owner and receiver hooks. 1 GB over loopback on the LOQ: 6.1 s, identical.

## Limits
1,024 top-level items and 100,000 files a copy, any folder depth (Windows' path length is the
limit), 2 GB by default (any size allowed). An archive is one file.

## Not in v1
Mac/Linux senders or receivers, drag-and-drop across the edge, resume after a dropped link
(the transfer restarts), files passed on through a chain of three machines, pasting straight from
the network without the drop folder (virtual files: possible later, see the 2026-11-19 plan).
