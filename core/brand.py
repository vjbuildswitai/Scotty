"""Who this app is: Scotty, a fork of Beamer that also carries copied files between Windows PCs.

Upstream's strings say "Beamer" and keep saying it in the source, so merging upstream stays easy;
`rebrand` turns the name into Scotty as each string is shown. Strings about upstream Beamer itself
(an older or newer Beamer on another machine, Beamer 1.4 or 1.5.0, the Mac's Beamer Tunnel) keep
the name, because there it means that program.

The wire still says what upstream says (its version in `hello`, its pairing names), so Scotty and
stock Beamer keep talking to each other. Scotty's own version is VERSION here; upstream's is the
repository's VERSION file, which is what peers see.
"""

import re

NAME = "Scotty"
UPSTREAM_NAME = "Beamer"
VERSION = "1.0.0"
REPOSITORY = "vjbuildswitai/Scotty"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}"
RELEASES_URL = f"{REPOSITORY_URL}/releases"
UPSTREAM_URL = "https://github.com/kalkman-code/beamer"
UPSTREAM_AUTHOR = "Toby George Read Kalkman (Kalkman Code)"

_WORD = re.compile(r"\bBeamer\b")
# Where "Beamer" names upstream's program on some machine, not this app.
_UPSTREAM = re.compile(
    r"older Beamer|newer Beamer|Beamer versions|Beamer 1\.\d|to 1\.\d|Beamer Tunnel|"
    r"Beamer on the two machines|Beamer on it|Beamer on \{name\}|Beamer\.app|/Applications/|Based on Beamer|different Beamer|as a Beamer|like Beamer|'s Beamer")


def rebrand(message: str, shown: str) -> str:
    """`shown` (the translation of `message`) with Beamer as Scotty, unless `message` is about
    upstream Beamer itself."""
    if not isinstance(shown, str) or "Beamer" not in shown or (isinstance(message, str) and _UPSTREAM.search(message)):
        return shown
    return _WORD.sub(NAME, shown)
