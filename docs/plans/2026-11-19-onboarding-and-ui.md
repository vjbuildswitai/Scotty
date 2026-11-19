# Plan: Easy first run and a friendlier window

- Track: scotty-ux
- Status: draft
- Approved by VJ: -
- Branch: feat/scotty-1.1   PR: -

## Goal
Someone who has never heard of a software KVM installs Scotty on two laptops and is moving the
pointer and pasting files across in under 3 minutes, without reading anything long. The window
shows what matters (am I connected, where is the other PC, what can I do) and keeps the rest one
click away.

## What is wrong today (from renders of every page, 1100x760)
- No first run: a new user lands on a settings page with two pairing buttons and paragraphs.
- Every control carries a sentence of explanation; Overview is a long scroll of cards.
- Status ("Waiting") is a small dot top-left; nothing says what to do about it.
- Problems (network set to Public, firewall, other PC asleep) show as text, not fixes.

## What changes
1. **Setup guide on first launch** (also from tray "Set up another PC"), full-window, one
   question per step, big visuals, Back/Next:
   - Welcome: one line and an animation of a pointer crossing between two laptops.
   - "Is the keyboard and mouse plugged into this PC?" Yes / No (sets who sends input).
   - "Open Scotty on your other PC": shows this PC's name and a 6-digit code, or finds the other
     PC nearby (existing CPace pairing and nearby discovery; nothing new on the wire).
   - "Where is it?": drag the other laptop left, right, above or below (writes the same layout the
     Crossing page edits).
   - Checks with one-click fixes: Wi-Fi set to Private, firewall rules present, the other PC
     reachable; each shows a tick or a Fix button.
   - "Try it": move the pointer to the edge; Scotty detects the first crossing and celebrates.
   - Extras: files (drop folder, on by default) and head turn (if that plan ships), each
     one switch with a one-line explanation.
2. **Home** replaces the top of Overview: a status hero with the two machines drawn as they sit,
   a live line showing which one has input, and a plain sentence ("Connected to LAPTOP-2, on your
   right"). When something is wrong, the hero turns amber and gives the fix button.
3. **Quieter settings**: the explanation under each control moves into a small (?) that shows it on
   hover or click; only warnings stay inline. Machine rows become compact cards with the common
   actions visible and the rest under "...".
4. **Tray menu**: status line, Send to <PC>, Pause, Head turn on/off, Open drop folder, Settings.
5. **Look**: keep Beamer's structure and fonts (upstream's design system, so its updates still
   merge) and add Scotty's layer: brand colour, larger hit targets on Home and the guide, short
   transitions (150-200 ms) between guide steps and on state changes, and dark/light parity.
   **Before coding the look, I make a clickable design mock of the guide and Home for VJ to
   approve.**

## Files that change
- `win_app/onboarding_win.py` - new: the setup guide (QStackedWidget of steps, animations).
- `win_app/home_win.py` - new: status hero widget and its states.
- `win_app/health_win.py` - new: checks (network category via `INetworkListManager`, firewall rules
  via `firewall_win`, reachability via the link state) and their fixes (the fixes that need
  Administrator ask through UAC once).
- `win_app/kvm_bridge_win.py` - show the guide when unpaired on first launch; Home at the top of
  Overview; (?) disclosure for notes; tray menu entries.
- `win_app/widgets.py` - `InfoTip` (the (?) control), `StepPage`, `ChecklistRow`.
- `win_app/tokens.py` / `theme.py` - Scotty accent and the few new sizes.
- `win_app/app_config.py` - `onboarded` flag in `scotty.json`.
- `locales/it.po` and `beamer.pot`; `README.md` screenshots; `TESTING.md` first-run steps.
- Upstream page tests that assert the inline notes are updated where the note moves into (?).

## Order of work
1. Design mock (guide + Home, light and dark) -> VJ approves the look.
2. Health checks (pure logic first, tested), then Home hero.
3. Setup guide, step by step, each with a test that drives it offscreen.
4. (?) disclosures across pages; tray menu.
5. Polish pass at 1100x760, 800x600 and 320 px wide, English, Italian and pseudo-locale.

## Tests that prove it
- New: guide flow test (fresh settings -> guide shows; finishing writes `onboarded`, layout and
  pairing exactly as the existing pages would), health check tests (Public network -> amber + Fix),
  Home state tests (connected / waiting / problem).
- Existing: every page and i18n layout test, including the narrow-width overlap test.
- Manual: a first-run on the second laptop from a fresh zip, timed; target under 3 minutes.

## Risks
- Kalkman's upstream changes to Overview will conflict more; Home is a separate widget inserted
  at one point to keep that small.
- Fixes that change Windows settings (network category, firewall) need Administrator; never done
  without the user pressing the button and accepting UAC.

## Rollback
- The guide is skipped when `onboarded` is true; Home can be hidden by reverting one insertion.

## Deviations
-
