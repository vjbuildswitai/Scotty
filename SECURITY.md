# Security

Beamer sends your keystrokes, pointer and clipboard between machines, so the link between them
matters. This is what it protects, what it does not, and how to report a problem.

## What the link protects

- **Every frame is encrypted and authenticated.** Beamer 1.5.0 uses wire version 6. Each connection
  exchanges fresh X25519 public keys and random nonce prefixes. The two directions get separate
  keys, derived with HKDF-SHA256 from the shared token and the X25519 result. PyNaCl provides
  X25519 and ChaCha20-Poly1305 through libsodium; HKDF-SHA256 uses Python's standard library.
  Frames are sealed with ChaCha20-Poly1305.
- **A later token leak does not decrypt a recorded 1.5.0 connection.** The connection key also
  depends on each side's fresh X25519 secret, which is discarded after key setup. A token is still
  sensitive: someone who gets it can act as that paired machine while they have it.
- **The token is never sent.** It is used locally to identify the pair and derive connection keys.
- **Frames cannot be replayed or reordered within a connection.** Each frame carries a counter the
  receiver requires to advance by one. A repeated, dropped or reordered frame ends the connection.
  A recorded connection also fails when sent again because a new connection has fresh keys.
- **Pairing uses a short-lived six-digit code.** The machines run CPace, a password-authenticated
  key exchange, to agree a token. The code is not sent over the network, and a recorded exchange
  cannot be checked against a list of possible codes offline. A code is accepted once and expires
  after a minute. The exchange is written out in [PAIRING.md](PAIRING.md).
- **Traffic stays on your network.** Paired machines talk directly. There is no account, relay
  server or telemetry. The update check makes an ordinary HTTPS request to GitHub's public releases
  API once a day; it sends no Beamer data, though GitHub sees the address the request comes from.
  Check for updates on Overview turns it off. Windows firewall rules apply to Private networks
  only.
- **Unauthenticated connections are limited.** A peer has five seconds and a 4KB first frame to
  authenticate, and Beamer holds only a small number of unauthenticated connections at once.

## Files (Scotty)

Scotty adds copied files on their own connection, TCP 24822. Design: FILES.md; wire: WIRE.md
section 11; code: `core/filechannel.py`.

- **A one-time ticket, only inside the link above.** Each copy gets a fresh 16-byte transfer id
  and 32-byte ticket, sent in the `files` manifest over the paired, encrypted link. The file
  connection never carries the ticket.
- **Fresh keys per connection and per direction.** Each end sends 32 random bytes; each direction's
  key is HKDF-SHA256 over the ticket, with both randoms as salt and the transfer id and direction
  as info. Frames are NaCl SecretBox (XSalsa20-Poly1305) with a counter nonce, so a replayed,
  dropped, reordered or reflected frame fails and ends the connection, and no key or nonce is ever
  reused. A connection naming an unknown transfer is closed with nothing sent; one naming a known
  transfer but lacking the ticket gets a 7-byte greeting and 32 random bytes, and its first frame
  fails to open.
- **Short-lived, single-use, one peer.** An offer stops working once every byte of it has been
  sent (whether or not the other PC confirms), as soon as a newer copy is offered to that PC, or
  after 10 minutes. It is served only to the address of the PC it was offered to (host names
  resolved; IPv4 and IPv6); with no known address nothing is offered at all.
- **Nothing to talk to unless it is wanted.** Scotty only listens on 24822 once it is paired. A
  connection from an address with nothing on offer to it is closed straight away, before any
  thread or byte is spent on it; an address that is gets at most 2 connections, 8 in all, and each
  has 10 seconds in total (not per read) to send its greeting and prove it holds the ticket.
- **Nothing outside what was copied.** The sender serves its own listing by index. Symbolic links
  and junctions inside copied folders are skipped. Each file's size and modified time are checked
  again just before sending.
- **Nothing outside the holding folder, and no disguised names.** Every received name is checked:
  no `..`, drive, `:` stream, control character, device name (`CON`, `NUL`, `COM1`..., also
  `CON .txt`), trailing dot or space, invisible formatting character (a right-to-left override
  can make `report‮fdp.exe` look like a PDF), more than 255 UTF-16 units, or two names that differ
  only by case. Partial files are numbered by their place in the listing in a folder of their own,
  so no listed name can collide with one; each moves into place with a rename that refuses to
  overwrite, so two names the drive treats as one end the transfer instead of losing a file.
  Files move into the holding folder only when every SHA-256 matches and the count and bytes add
  up; a failed or cancelled transfer leaves nothing.
- **Bounded.** The receiver checks its size limit and free disk space (leaving 512 MB for
  Windows) before connecting; at most 100,000 files and 1,024 top-level names a copy; one fetch at
  a time, the newest replacing any waiting, so a flood of copies cannot pile up work.
- **Its own folders only.** Received files go in dated folders that Scotty marks as its own, and
  only those are ever cleared; a folder of yours named like a date is never touched.
- **Taken only from the PC in charge.** A PC takes a manifest only from the PC driving it, or from
  the PC it has just handed the pointer to, once, within 10 seconds.
- **Marked as from another computer.** Received files get the Windows mark of the web (ZoneId=3)
  unless turned off, so SmartScreen and Office Protected View treat them like a download. The mark
  lives on NTFS drives: a holding folder on FAT32 or exFAT cannot keep it (Scotty says so when a
  transfer arrives), and pasting onto such a drive drops it, as it does for any download.
- **Portable passphrase**: Argon2id at moderate strength (256 MiB a guess); a vault written by an
  older version is rewritten at that strength on first unlock.

## Head turn and the camera (Scotty)

- **Off by default.** While off, Scotty never opens the camera and never loads OpenCV.
- **On this PC only.** Only the PC with the keyboard and mouse uses its webcam; the other PC's
  camera is never touched.
- **Nothing kept, nothing sent.** Each frame is shrunk to 320 px, searched for one face, turned
  into two numbers (how far the nose sits sideways and below the eyes) and dropped. No picture is
  written, logged or sent. Calibration saves only those numbers for each screen, in `scotty.json`.
- **Nothing new on the network.** A head turn moves input the way the jump shortcut does; the other
  PC cannot tell the two apart, and no camera data or new message travels between them.
- **Never steals typing.** No switch while a key or mouse button is held, within 0.8 s of a key
  press, or while you look down at the keyboard.
- **Windows stays in charge.** The camera light is on while head turn runs. If Windows privacy
  settings block the camera for desktop apps, Scotty says so and does not try to get round it.
- The face model (YuNet, MIT licence) ships inside Scotty; nothing is downloaded at run time.

## What it does not protect against

- **Someone on your network can see that Beamer is running.** Machines announce their name and
  connection port on the local network. Anyone on that network can try to reach the pairing
  service while a code is on screen.
- **Someone on your network can interrupt pairing.** A failed attempt can use up the displayed
  code, so you may need to show a new one. The attempt does not reveal the code or let the person
  join the pair.
- **Pairing does not prove a machine's network address.** The address comes from local discovery,
  which another machine on the network can imitate. That can stop a connection or point Beamer at
  the wrong address, but the encrypted link still requires the paired token.
- **A machine with the token is trusted.** It can type and click in applications that accept
  synthetic input on the paired machine. On Windows, Beamer runs elevated so it can reach elevated
  windows; it cannot control the secure desktop. Treat the token like a password.
- **Malware on either machine.** Software that can read your keyboard or Beamer's local settings
  can already act as you or the paired machine.
- **Traffic analysis.** Encryption hides the contents, not when machines talk or the size and timing
  of frames. The protocol version and a stable key identifier for the pair are sent in the clear,
  so a network observer can recognise connections between the same pair of machines.
- **A paired PC can send you files.** Within your size limit, into the holding folder, marked as
  from another computer; it cannot place them anywhere else or run them. The sizes and timing of a
  file transfer are visible on the network, not its names or contents.
- **Old Beamer versions cannot connect to 1.5.0.** Version 1.5.0 uses wire version 6; Beamer 1.4.x
  uses version 5. Update both ends and pair the machines again.

## Reporting a vulnerability

Please report privately, not in a public issue. For Scotty's file transfer or anything Scotty
changed, use the Security tab on [github.com/vjbuildswitai/Scotty](https://github.com/vjbuildswitai/Scotty).
For the link and pairing themselves, which come from Beamer, on
[github.com/kalkman-code/beamer](https://github.com/kalkman-code/beamer), open the Security tab and
choose Report a vulnerability. Say what you found, how to reproduce it, and which version and
platform. Beamer is made by one person, so there is no fixed response time.
