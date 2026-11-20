"""Build helper (not bundled): Scotty's version and the exe's version resource, for both specs.

The version is core/brand.py's VERSION (Scotty's own); the repository VERSION file stays
upstream's, which is what peers see on the wire. Signing services check that the product name
matches the project and that the product version is the one being released.
"""

import re
from pathlib import Path


def scotty_version(source_dir) -> str:
    text = (Path(source_dir).parent / "core" / "brand.py").read_text(encoding="utf-8")
    match = re.search(r'^VERSION = "(\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)"$', text, re.MULTILINE)
    if match is None:
        raise SystemExit("core/brand.py has no usable VERSION line")
    return match.group(1)


def version_info(source_dir):
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )
    version = scotty_version(source_dir)
    numeric = tuple(int(part) for part in version.split("-", 1)[0].split("."))
    numeric += (0,) * (4 - len(numeric))
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numeric, prodvers=numeric, mask=0x3F, flags=0, OS=0x40004,
                          fileType=1, subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable("080904B0", [
            StringStruct("CompanyName", "Scotty (based on Beamer by Kalkman Code)"),
            StringStruct("FileDescription", "Scotty"),
            StringStruct("FileVersion", version),
            StringStruct("InternalName", "Scotty"),
            StringStruct("LegalCopyright", "GPL-3.0-or-later"),
            StringStruct("OriginalFilename", "Scotty.exe"),
            StringStruct("ProductName", "Scotty"),
            StringStruct("ProductVersion", version),
        ])]), VarFileInfo([VarStruct("Translation", [0x0809, 1200])])],
    )
