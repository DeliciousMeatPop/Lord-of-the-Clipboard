"""Generate a Windows version-resource file for PyInstaller's --version-file.

Reads the version from argv[1] (or the LOTC_VERSION env var) and writes
packaging/file_version_info.txt so the built .exe carries real version metadata
(right-click ▸ Properties ▸ Details). Non-numeric suffixes like '-beta' are
kept in the string fields but stripped from the numeric (a, b, c, d) tuple.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

version = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LOTC_VERSION", "0.0.0")).strip()

nums = re.findall(r"\d+", version)
while len(nums) < 4:
    nums.append("0")
a, b, c, d = (int(nums[i]) for i in range(4))

TEMPLATE = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, {d}),
    prodvers=({a}, {b}, {c}, {d}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'DeliciousMeatPop'),
        StringStruct('FileDescription', 'Lord of the Clipboard'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'LordOfTheClipboard'),
        StringStruct('OriginalFilename', 'LordOfTheClipboard.exe'),
        StringStruct('ProductName', 'Lord of the Clipboard'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

out = Path(__file__).resolve().parent / "file_version_info.txt"
out.write_text(TEMPLATE, encoding="utf-8")
print(f"wrote {out} for version {version} -> ({a}, {b}, {c}, {d})")
