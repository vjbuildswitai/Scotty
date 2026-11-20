# Plan: six features (wake, lock together, send to, updates, drag across, clipboard history)

- Track: scotty-1.2
- Status: approved (VJ, chat, 2026-11-20: "start a plan and implement all 6 features")
- Branch: feat/scotty-1.2 (from feat/scotty-1.1 once its PR is open)   PR: -

## Rules that hold for all six
- Each new message is gated on its own capability in `hello`/`welcome` (`core/link.py` `_CAP_FOR`),
  documented in WIRE.md section 12. Stock Beamer and older Scotty never see them.
- Anything a peer sends is untrusted input: validated in `core/protocol.py` read functions with
  size caps, tested with malformed and oversized input.
- Each feature is a setting on Overview with an Italian translation; SECURITY.md gets a line per
  feature saying what a paired PC can and cannot make this PC do.
- Order is smallest and safest first. Each lands with its tests and `verify.sh` green.

## 1. Lock together (small)
- When this PC locks (Win+L, lid, timeout), peers that have it on lock too. Unlock never travels.
- Windows: `WTSRegisterSessionNotification` on the window, `WTS_SESSION_LOCK` -> send
  `{"type":"lock"}`; receiving -> `LockWorkStation()`.
- Cap `scotty_lock`. Setting "Lock with the other PC", default on. Rate limit: one lock per 5 s.
- Security: a paired PC can lock this one (harmless, the user unlocks); it cannot unlock it.

## 2. Send to the other PC (small to medium)
- Explorer: "Send to > Scotty: <PC name>" shortcuts in the user's SendTo folder, one per paired
  PC, kept in step with pairings. `Scotty.exe --send-to <peer id> <paths...>` hands the paths to the
  running Scotty (its single-instance pipe); Scotty offers them as it does on a crossing.
- Message `files_push` = the existing files manifest with `pushed: true`; the receiver pulls into
  the drop folder as today, then shows "3 files from LAPTOP-1: Open folder". Same channel, same
  limits, same checks, mark of the web.
- Link hotkey (default Ctrl+Alt+L, changeable): sends the clipboard's URL; the other PC opens it in
  its default browser. Only `http`/`https`, at most 2,000 characters, no credentials in the URL;
  anything else shows a toast instead of opening. Cap `scotty_send`.
- Security: today a PC accepts files only from the PC driving it. A push is accepted from any
  paired PC only while "Accept files and links sent from my other PCs" is on (default on), within the
  size limit, into the holding folder only; links open only after the checks above.

## 3. Shared clipboard history (medium)
- The last 20 clipboard items (text and images) from this PC and from peers' clipboards as they
  arrive with a crossing. Hotkey (default Ctrl+Alt+V) opens a small picker at the pointer; Enter
  puts the item on the clipboard.
- Kept in memory only, cleared on lock and on quit; never written to disk or logs. Items a password
  manager marks private (`ExcludeClipboardContentFromMonitorProcessing`,
  `CanIncludeInClipboardHistory = 0`) are never kept. Nothing new on the wire.

## 4. Wake the other PC (medium; hardware decides)
- On link up, each PC sends its network adapters' MAC addresses (`machine_info`, cap `scotty_wake`);
  stored with the pairing.
- When the pointer is pushed at the edge of a PC that is not connected, or head turn faces it,
  Scotty sends a Wake-on-LAN magic packet (UDP broadcast, port 9, to the local subnet) and shows
  "Waking LAPTOP-2...". Also a "Wake" item in the tray.
- Honest limit: many laptops do not wake from Wi-Fi sleep (Modern Standby). Scotty tests it once in
  the setup guide and says whether this pair can do it. On wired Ethernet it usually works.
- Security: the packet carries only the MAC; it reveals nothing and controls nothing else.

## 5. One-click updates (medium; needs signed releases)
- The update check already finds a newer release. New: "Update now" downloads the zip, checks its
  SHA-256 against the release notes and the Authenticode signature of `Scotty.exe` inside
  (`WinVerifyTrust`, publisher must match the current exe's), then a small updater swaps the folder
  after Scotty exits and starts the new one. Installed copies run the signed installer instead.
- Refuses anything unsigned, signed by someone else, or from another repository. Until releases are
  signed, the button stays "Open the release page".

## 6. Drag a file across the edge (large; Windows makes this hard)
- Sender: while a drag is in progress (mouse button held, Explorer drag image active) and the
  pointer crosses, Scotty reads the dragged files from the drag's data object (OLE
  `IDataObject` via the drop-target it registers on a transparent edge window), and sends them as on
  a crossing.
- Receiver: when the transfer lands, Scotty starts a real drag (`DoDragDrop` with `CF_HDROP`) under
  the pointer while the button is still held, so you drop where you want.
- Risk: OLE drag across processes and elevated windows is fiddly. If the full gesture is not
  reliable on VJ's laptops, the fallback ships: drop files on the screen edge to send them to the PC
  beyond it. Decision after a spike of two days.

## Order
1, 2, 3 (no hardware questions), then 4 (needs the two-laptop test), 5 (needs signing), 6 (spike).

## Tests that prove it
- Pure parts in core with tests: message validation for `lock`, `files_push`, `open_url`,
  `machine_info`; URL rules; magic packet bytes; clipboard history ring and privacy rules; update
  verification decisions (hash, publisher, repository).
- Windows parts with fakes: session notification -> lock message; SendTo shortcut set kept in step;
  updater swap on a temp folder.
- Two-laptop checks in TESTING.md for each feature.

## Rollback
- Each feature is a setting, and each has its own capability; turning one off or reverting its
  commit leaves the others.

## Deviations (recorded while building)
- **One capability, not one each.** A peer refuses a `hello` listing more than `MAX_CAPS` (16) and
  Scotty already sends 14, so `lock`, `files_push`, `open_url` and `machine_info` all ride
  `scotty_extras` (WIRE.md section 12). Each feature still has its own switch, in `scotty.json`'s
  `extras` section, so turning one off still leaves the others. Rollback per feature is its switch
  or its commit; the capability stays.
- **Lock together** is in `win_app/lock_win.py`: `LockTogether` (switch, one lock per 5 s each way,
  no echo of a lock a peer caused) and `SessionWatcher` (Qt native event filter for
  `WM_WTSSESSION_CHANGE`). Lock messages go out on both the links this PC opened and the links
  opened to it; the rate limit absorbs the duplicate.
