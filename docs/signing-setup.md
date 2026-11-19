# Signing setup: what VJ does once

Two free routes (chosen 2026-11-19): the Microsoft Store (Microsoft signs; no warning at all) and
SignPath Foundation for the GitHub download. See `docs/plans/2026-11-19-signed-releases.md`.

## 1. Microsoft Store (about 15 minutes, then 1-3 days review per submission)

1. Go to https://storedeveloper.microsoft.com, choose **Individual developer**, sign in with your
   personal Microsoft account and verify your identity (free).
2. In Partner Center, **Apps and games, New product, MSIX or PWA app**, reserve the name **Scotty**.
   If it is taken, try "Scotty KVM".
3. Open the product, **Product management, Product identity**. Send Claude the three values shown:
   `Package/Identity/Name`, `Package/Identity/Publisher` and `Package/Properties/PublisherDisplayName`.
   They go into the package manifest; the package cannot be built without them.

Claude then builds the MSIX on GitHub (the Windows SDK is there, so nothing installs on the LOQ),
you install it on both laptops to test, and you press Submit in Partner Center.

## 2. SignPath Foundation (form takes 10 minutes; acceptance can take weeks)

One condition matters first: **the project must already be released** in the form to be signed.
So SignPath reviews Scotty only after a first release exists on GitHub (see the choices in the
chat). Then:

1. Turn on two-factor authentication on GitHub if it is not on (required for everyone who signs).
2. Apply at https://signpath.org/apply with:
   - Project name: Scotty
   - Repository: https://github.com/vjbuildswitai/Scotty
   - Licence: GPL-3.0 (OSI-approved), inherited from Beamer
   - Description: "Free software KVM for Windows: one keyboard and mouse across PCs on the same
     network, copied files that follow the pointer, and optional switching by head turn. Built
     on Beamer (GPL-3.0, Kalkman Code), whose Windows installer is signed by its author."
   - Download page: https://github.com/vjbuildswitai/Scotty/releases
   - Code signing policy: https://github.com/vjbuildswitai/Scotty/blob/main/CODE-SIGNING.md
   - Build system: GitHub Actions, `.github/workflows/release.yml`
   - Artifacts: `Scotty-Portable-<version>-windows-x64.zip` (Scotty.exe inside)
3. When accepted, in SignPath: create the project (slug `scotty`), paste
   `.signpath/artifact-configuration.xml` as its artifact configuration, add GitHub as the trusted
   build system, and create a signing policy (slug `release-signing`) with yourself as approver.
4. In GitHub, repository **Settings, Secrets and variables, Actions**: secret
   `SIGNPATH_API_TOKEN`; variables `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG` (`scotty`),
   `SIGNPATH_POLICY_SLUG` (`release-signing`).

From then on: push a tag `vX.Y.Z`, approve the signing request SignPath emails you, and publish
the draft release GitHub makes.
