# Plan: Signed releases, no "unknown publisher"

- Track: scotty-release
- Status: draft
- Approved by VJ: -
- Branch: feat/scotty-1.1   PR: -

## Goal
People who download Scotty see a named, verified publisher and no "Windows protected your PC"
block. Two channels: the Microsoft Store (Microsoft signs it; no SmartScreen warning at all) and a
signed zip/installer on GitHub for people who do not use the Store.

## What signing can and cannot do (Nov 2026)
- An unsigned exe gets the strongest SmartScreen block. A signed one names the publisher and proves
  nobody changed the file, but a **new** signature still shows a milder warning until Microsoft has
  seen enough clean downloads. EV certificates stopped skipping that in 2024, so paying for EV buys
  nothing here.
- Only the Microsoft Store (MSIX) installs with no warning from day one: Microsoft re-signs the
  package. Registration is free for individuals.
- Azure Artifact Signing ($9.99/month) only takes individual developers in the USA and Canada, so
  it is out for VJ in India.

## Routes
1. **Microsoft Store, MSIX** (free, no warning). VJ registers a free individual developer account
   (personal Microsoft account + ID check), reserves the name "Scotty". I package the app as MSIX
   (PyInstaller folder + `AppxManifest.xml`, `runFullTrust`, firewall rules declared in the
   manifest) and submit through Partner Center. The Store edition is the portable feature set: no
   Secure Desktop helper and no control of Administrator apps (a packaged app cannot get UIAccess),
   which the About box already explains for portable.
2. **GitHub download, signed by SignPath Foundation** (free for OSI-licensed open source; Scotty is
   GPL-3.0). VJ applies at signpath.org; once accepted, CI builds the zip and installer on GitHub
   Actions and sends them to SignPath, which signs them only if they came from this repository's
   workflow. Publisher shown: "SignPath Foundation". The README and a `CODE-SIGNING.md` carry the
   credit line the programme requires.
3. **Alternative to 2: Certum "Open Source Developer" certificate** (about EUR 69, 459-day
   validity): publisher shows "Open Source Developer, Vijayaraj Anandan". VJ verifies his ID with
   Certum; signing runs on his laptop through SimplySign (key stays in Certum's cloud HSM), never in
   CI and never in this repository.

Recommendation: 1 + 2, both free. 3 only if VJ wants his own name as publisher on GitHub downloads.

## Files that change
- `win_app/msix/AppxManifest.xml`, `win_app/msix/Assets/*` (tiles from `Scotty.svg`) - new.
- `win_app/build_msix.ps1` - builds `Scotty-<version>.msix` from the PyInstaller folder with
  `makeappx` (Windows SDK); unsigned for Store upload, test-signed for local install.
- `core/portable_runtime.py` / `win_app/kvm_bridge_win.py` - detect "packaged" (Store) like
  portable: settings under the package's LocalState, no Run key, no scheduled tasks, no installer
  maintenance; firewall rules come from the manifest.
- `.github/workflows/release.yml` - on a tag: build zip + installer, submit to SignPath, attach the
  signed files to a **draft** release (VJ publishes).
- `CODE-SIGNING.md`, `README.md` - signing policy and credit.
- Tests: `win_app/tests/test_packaged_runtime.py` (packaged mode never writes Run keys, tasks or
  firewall rules); manifest test (capabilities limited to `runFullTrust` + `internetClientServer` +
  `privateNetworkClientServer`, webcam only if head-turn ships).

## Order of work
1. VJ: Store developer account; SignPath application (I fill the form text; he submits).
2. MSIX packaging + packaged-mode detection + tests; local install of a test-signed MSIX on both laptops.
3. Store submission (VJ clicks submit in Partner Center; certification takes 1-3 days).
4. SignPath workflow once accepted (acceptance can take weeks).
5. Until then: 1.0.0 goes out as is, unsigned, with the README saying so and how to check the
   SHA-256.

## Tests that prove it
- `bash scripts/verify.sh` green.
- MSIX installs on a clean Windows 11 (the second laptop), pairs with the LOQ, files cross.
- `Get-AuthenticodeSignature` on CI-signed files: Valid, publisher SignPath Foundation.

## Risks
- Store review may question input capture and injection (a KVM). Mitigation: clear listing text;
  Mouse without Borders-style apps are in the Store.
- MSIX runs with a virtualised registry and AppData: settings migrate from a portable copy only if
  the user imports them.
- SignPath requires every signed build to come from CI; local builds stay unsigned by design.

## Rollback
- Store: pull the listing in Partner Center. GitHub: delete the release asset; the unsigned zip
  path keeps working.

## Deviations
-
