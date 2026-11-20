# Contributing to Scotty

Scotty is made by one person, Vijayaraj Anandan, in spare time. Issues and pull requests are
welcome and read; there is no promise that every idea gets built.

## Reporting a problem

Open an issue with the **Bug report** form. It asks for:

- the Scotty version on each PC (Overview, bottom left, or About in the tray menu);
- Windows version on each PC;
- what you did, what happened, what you expected;
- `Scotty.log` from each PC: tray menu, **Open log folder** (usually
  `%LOCALAPPDATA%\Scotty\Scotty.log`; next to `Scotty.exe` for the portable copy).

Security problems: do **not** open a public issue. See [SECURITY.md](SECURITY.md).

## Problems that are Beamer's

Scotty is built on [Beamer](https://github.com/kalkman-code/beamer). If something also happens in
Beamer itself (crossing, keyboard layouts, clipboard text and images, pairing), report it there
too, so the fix reaches both. Scotty's own parts are files across the edge, head turn, the setup
guide and the Windows packaging.

## Pull requests

- One change per pull request, into `main`, with a test that fails without it.
- `bash scripts/verify.sh` must pass (Git Bash on Windows). Paste its last lines in the PR.
- Anything that changes the file channel keeps every promise in SECURITY.md (Files) and adds a
  test for it.
- New on-screen text goes through `tr()` and gets an Italian line in `locales/it.po`
  (`python tools/i18n_extract.py`, then `--check`).
- Never change what goes over the wire for existing messages: stock Beamer must keep talking to
  Scotty (WIRE.md).

By contributing you agree your work is released under the GPL-3.0, the licence Scotty and Beamer
use. There is no separate contributor agreement.
