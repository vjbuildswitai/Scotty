# Scotty changelog

## 1.0.0 (unreleased)

Based on Beamer 1.5.21.

- **Copied files follow the pointer** between Windows PCs: copy in Explorer, cross, Ctrl+V.
  Files and folders of any depth, up to 1,024 top-level items and 100,000 files a copy, 2 GB by
  default (raisable). Their own encrypted connection on TCP 24822, so input never waits.
- **One copy, not two**: received files wait in `Downloads\Scotty Drop` and pasting moves them out;
  what is never pasted is cleared after 7 days (setting).
- **Progress and Cancel on both PCs.**
- **Received files are marked as from another computer** (Windows SmartScreen, Office Protected
  View), on by default.
- **Security**: a one-time ticket inside Beamer's encrypted link, fresh keys per connection,
  single-use offers that a newer copy withdraws, peer address checks (names resolved, IPv6), no
  listener until paired, at most 2 file connections per PC and 8 in all with 10 seconds in total to
  authenticate, strict name checks (no path tricks, device names or invisible right-to-left
  characters) so nothing lands outside the holding folder or passes for another file type, and
  a cleaner that only ever touches folders Scotty made. Reviewed independently before release;
  see SECURITY.md.
- The Files settings stack cleanly in a narrow window and in longer translations.
- **Portable passphrase** protection raised to Argon2id moderate; older portable folders upgrade on
  first unlock.
- Its own name, icon, version, install folder, settings, sign-in task, firewall rules and update
  checks (from this repository's releases), so it never touches an installed Beamer.
