#!/usr/bin/env python3
"""
Patch Dawn's build_dawn.py to enable X11 support on Linux.

Skia chrome/m144 doesn't pass -DDAWN_USE_X11=ON to Dawn's CMake,
causing X11 surfaces to be unsupported. Fixed on Skia main but not m144.
"""

import sys
from pathlib import Path


def apply_patches(skia_dir: Path):
    build_dawn_py = skia_dir / "third_party" / "dawn" / "build_dawn.py"
    content = build_dawn_py.read_text()

    if "DAWN_USE_X11" in content:
        print("  build_dawn.py already has DAWN_USE_X11")
        return

    # Insert before "env = os.environ.copy()"
    old = "  env = os.environ.copy()"
    new = '  if target_os == "Linux":\n    configure_cmd.append("-DDAWN_USE_X11=ON")\n\n  env = os.environ.copy()'

    if old not in content:
        print("  ERROR: Could not find 'env = os.environ.copy()' in build_dawn.py")
        sys.exit(1)

    content = content.replace(old, new, 1)
    build_dawn_py.write_text(content)
    print("  Patched build_dawn.py: added -DDAWN_USE_X11=ON for Linux")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <skia_source_dir>")
        sys.exit(1)
    apply_patches(Path(sys.argv[1]))
