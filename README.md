<p align="center"><img src="win_app/Scotty.svg" width="96" alt="Scotty"></p>

<h1 align="center">Scotty</h1>

<p align="center">One keyboard and mouse across your Windows PCs, and copied files that follow the pointer.</p>

Scotty is free, open-source software for two or more Windows 10 or 11 PCs on the same network. Move
the pointer off the edge of one screen and it carries on onto the next PC; the keyboard goes with
it. Copy files or folders in Explorer on one PC, move across, press Ctrl+V, and they arrive. Or
turn on head turn and just look at the other PC's screen.

Scotty is built on [Beamer](https://github.com/kalkman-code/beamer) by Toby George Read Kalkman
(Kalkman Code), which does the keyboard, mouse and clipboard. Scotty adds the files. Beamer's own
guide, for everything the two share, is in [docs/BEAMER.md](docs/BEAMER.md).

## Download

Get the latest from the [releases page](https://github.com/vjbuildswitai/Scotty/releases/latest):
`Scotty-Portable-<version>-windows-x64.zip` runs from any folder without installing. Put it on each
PC. Releases are signed; see the [code signing policy](CODE-SIGNING.md). A newly signed release can
still get a SmartScreen notice for its first days while Windows learns it; the publisher name it
shows tells you it is genuine.

## Head turn (optional)

Turn on **Switch PCs by turning your head** on Overview and calibrate once (look at this screen,
then at the other PC's). From then on, turning to face the other laptop sends the keyboard and
pointer there. It uses the webcam of the PC your keyboard and mouse are plugged into, never
switches while you type, and saves or sends no picture. Off by default; pause it from the tray.

## How it works

**Connect the keyboard and mouse to one PC only**, by Bluetooth or its USB dongle. That PC reads
them and Scotty sends what you type and how you move over your network to whichever PC the pointer
is on. Nothing needs pairing to the second PC. Both PCs must be on, awake and running Scotty, and
the one the keyboard is connected to has to stay awake, since everything passes through it.

**Pair once.** Open Scotty on both, choose Pair on one, type the six-digit code it shows on the
other. Arrange the screens on the Crossing page the way they sit on your desk.

**Set the Wi-Fi to Private** on both PCs (Settings, Network, your Wi-Fi, Private network). On a
Public network Windows blocks the connection.

On the other PC, the Windows sign-in screen and administrator prompts need that PC's own keyboard
unless the optional secure desktop service is installed (see docs/BEAMER.md).

## Sending files

1. Select files or folders in Explorer and press Ctrl+C (Ctrl+X works too; Scotty never deletes
   anything on the PC they came from).
2. Move the pointer to the other PC.
3. A small panel shows the files arriving, with Cancel. When it says they arrived, press Ctrl+V in
   any folder.

Files arrive first in a holding folder, `Downloads\Scotty Drop`, because Windows can only paste
files that are already on the PC. Pasting **moves** them out of it, so you end up with one copy,
in the folder you pasted into. On the same drive the move is instant. Anything you never paste is
cleared after 7 days. A second Ctrl+V does nothing, as after Cut; to copy them somewhere else too,
copy them again from where you pasted them.

The file bytes travel on their own connection (TCP port 24822), so the pointer stays smooth during
a big transfer. On 5 GHz Wi-Fi or a cable it is limited by the network, not by Scotty: 1 GB takes
about 6 seconds on one machine, and roughly 100 seconds over 144 Mbps Wi-Fi.

### Limits for one copy

| | |
|---|---|
| Items selected at the top | up to 1,024 (more: put them in one folder) |
| Files inside them, all folder levels | up to 100,000 |
| Folder depth | no limit of its own; Windows' path length is the limit (about 260 characters unless long paths are on) |
| Total size | 2 GB by default; raise it under Overview, Files (any size) |
| A zip or any archive | one file; Scotty never opens it |

Names Windows cannot create (with `:` `*` `?` and the like, or `CON`, `NUL` and other device
names) are refused before anything is sent, with the name in the message.

### Settings (Overview, Files)

- Copied files follow the pointer: on or off.
- Where received files go (the holding folder) and Open.
- Largest transfer, in GB.
- Clear files not pasted after, in days (0 keeps them).
- Mark received files as from another computer (on): Windows then asks before a received program
  runs, and Office opens received documents in Protected View, as for a download.

## Security

Someone on the same Wi-Fi should not be able to read, change or inject anything. In short:

- **Keyboard, mouse and clipboard** use Beamer's link: a six-digit pairing code (CPace, never sent),
  then fresh keys for every connection (X25519, ChaCha20-Poly1305), replay and reorder protection.
  See [SECURITY.md](SECURITY.md).
- **Files** need a one-time 256-bit ticket that only travels inside that encrypted link. The file
  connection never carries the ticket: both PCs derive fresh keys from it and random values for
  every connection (HKDF-SHA256, then NaCl SecretBox), and a ticket stops working once the files
  have arrived, or after 10 minutes. Every file is checked with SHA-256.
- **A PC only takes files from the PC driving it** (or the one it just handed the pointer to), only
  up to its size limit and free space, and never writes outside its holding folder.
- **A sending PC only serves what you copied**, by number from its own list; nothing else on its
  disk can be asked for. It accepts at most 8 connections at a time.
- **Firewall rules are for Private networks only.** Portable mode protects pairing keys with your
  passphrase (Argon2id, moderate strength, 12 characters or more).

Found a hole? Please report it privately (see [SECURITY.md](SECURITY.md)) rather than in an issue.

## Install instead of portable

From a clone, in PowerShell as the signed-in user: `win_app\Install-Scotty.ps1`. It builds
Scotty, installs it to `%LOCALAPPDATA%\Scotty`, adds a Start menu entry and the Private-network
firewall rules (24820, 24821 and 24822).

## Build and test

```powershell
cd win_app
.\build_portable.ps1      # dist\portable\Scotty-Portable-<version>-windows-x64.zip
```

`bash scripts/verify.sh` (Git Bash on Windows) runs every test and a real 1 GB transfer. A
five-minute manual check on two PCs is in [TESTING.md](TESTING.md).

## Credits and licence

Scotty is a fork of [Beamer](https://github.com/kalkman-code/beamer) 1.5.21 by Toby George Read
Kalkman (Kalkman Code), and like Beamer is free software under the
[GNU General Public License version 3](LICENSE). Scotty's changes are listed in
[CHANGELOG.md](CHANGELOG.md). Scotty and Beamer can be installed side by side but not run at the
same time (they use the same ports); each keeps its own settings and pairings.
