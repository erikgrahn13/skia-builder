#!/usr/bin/env python3
"""
Patch Dawn's D3D12 device initialization to make shared fence handle
creation non-fatal when the driver returns E_NOTIMPL.

On native Windows, CreateSharedHandle succeeds and behavior is unchanged.
On Wine/vkd3d, CreateSharedHandle on fences returns E_NOTIMPL (unimplemented
in vkd3d-proton). Without this patch Dawn fails RequestDevice entirely.
With this patch the same binary runs on both Wine and native Windows.

Target: third_party/externals/dawn/src/dawn/native/d3d12/DeviceD3D12.cpp
"""

import sys
import re
from pathlib import Path


def apply_patches(skia_dir: Path):
    target = (
        skia_dir
        / "third_party" / "externals" / "dawn"
        / "src" / "dawn" / "native" / "d3d12"
        / "DeviceD3D12.cpp"
    )

    if not target.exists():
        print(f"  WARNING: {target} not found, skipping fence handle patch")
        return

    content = target.read_text(encoding="utf-8")

    # Idempotency guard
    if "fenceHandleHr" in content:
        print("  DeviceD3D12.cpp: fence handle patch already applied, skipping.")
        return

    marker = '"D3D12 create fence handle"'
    if marker not in content:
        print(f"  WARNING: {marker} not found in DeviceD3D12.cpp — Dawn version may have changed. Skipping.")
        return

    lines = content.splitlines(keepends=True)
    new_lines = []
    patched = False

    for line in lines:
        if marker in line and "CreateSharedHandle" in line and "DAWN_TRY" in line:
            indent = len(line) - len(line.lstrip())
            pad = " " * indent

            m = re.search(r'CheckHRESULT\((.+),\s*"D3D12 create fence handle"', line, re.DOTALL)
            if m:
                expr = m.group(1).strip()
                new_lines.append(pad + "{ HRESULT fenceHandleHr = (" + expr + ");\n")
                new_lines.append(pad + "  if (FAILED(fenceHandleHr)) {\n")
                new_lines.append(pad + "    if (fenceHandleHr == E_NOTIMPL) {\n")
                new_lines.append(pad + "      // Driver does not implement shared fence handles (e.g. Wine/vkd3d).\n")
                new_lines.append(pad + "      // Skip gracefully — on real Windows this call never fails.\n")
                new_lines.append(pad + "    } else {\n")
                new_lines.append(pad + '      DAWN_TRY(CheckHRESULT(fenceHandleHr, "D3D12 create fence handle"));\n')
                new_lines.append(pad + "    }\n")
                new_lines.append(pad + "  } }\n")
                patched = True
                continue
        new_lines.append(line)

    if not patched:
        print("  WARNING: Could not locate the CreateSharedHandle fence line to patch.")
        return

    target.write_text("".join(new_lines), encoding="utf-8")
    print("  Patched DeviceD3D12.cpp: shared fence handle creation is now non-fatal (E_NOTIMPL tolerated)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <skia_source_dir>")
        sys.exit(1)
    apply_patches(Path(sys.argv[1]))
