# Code signing policy

Scotty's Windows releases are signed so you can check they came from this repository and were not
changed on the way to you.

- **Downloads from GitHub Releases:** free code signing provided by
  [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org)
  (once Scotty is accepted into the programme; until then releases are marked unsigned).
- **Microsoft Store:** signed by Microsoft when the Store publishes the package.

Every signed file is built from source on GitHub Actions by `.github/workflows/release.yml` from a
tagged commit on `main`; nothing built on a personal computer is ever signed. Each release is
approved by hand before signing.

## Team

| Role | Who | Responsibility |
|---|---|---|
| Author | Vijayaraj Anandan ([@vjbuildswitai](https://github.com/vjbuildswitai)) | Commits to this repository |
| Reviewer | Vijayaraj Anandan | Reviews every pull request from anyone else before it is merged |
| Approver | Vijayaraj Anandan | Approves each signing request |

Everyone in these roles uses multi-factor authentication for GitHub and SignPath.

Scotty is built on [Beamer](https://github.com/kalkman-code/beamer) by Kalkman Code (GPL-3.0),
whose Windows installer is signed by its author. Scotty is a visibly separate app with its own
name, icon, settings and releases.

## Privacy

Scotty does not send information anywhere you did not ask for:

- Keyboard, mouse, clipboard and files travel only between your own paired PCs on your local
  network, encrypted (see [SECURITY.md](SECURITY.md)).
- The update check asks GitHub's public releases API for this repository's latest version, once at
  start-up and once a day; turn it off on Overview. Nothing about you or your PCs is sent.
- Head turn, when you turn it on, uses this PC's webcam on this PC only: no picture is saved or
  sent (see SECURITY.md, "Head turn and the camera").
- There are no accounts, analytics, crash uploads or advertising.

Third-party components bundled with Scotty (Qt, PyNaCl, OpenCV, numpy, the YuNet face model) do
not contact the network from Scotty; their licences are in `THIRD-PARTY-NOTICES.txt` beside
`Scotty.exe`.
