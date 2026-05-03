"""
Build sculpt_kit.zip for Blender extension install.

Run with any Python 3.11+:
    python pack.py
or with Blender's bundled Python:
    "C:/Program Files/Blender Foundation/Blender 5.1/5.1/python/bin/python.exe" pack.py
"""
from __future__ import annotations

import pathlib
import zipfile

EXCLUDE_PARTS = {".git", "__pycache__"}
EXCLUDE_FILES = {".gitignore", "pack.py"}


def main() -> None:
    src = pathlib.Path(__file__).resolve().parent
    out = src.parent / f"{src.name}.zip"
    out.unlink(missing_ok=True)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(src.rglob("*")):
            if not f.is_file():
                continue
            if any(part in EXCLUDE_PARTS for part in f.parts):
                continue
            if f.name in EXCLUDE_FILES:
                continue
            arcname = f.relative_to(src)
            z.write(f, arcname)
            print(f"  + {arcname}")

    print(f">>> wrote {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
