#!/usr/bin/env python3
"""
Patch Dawn's D3D12 queue initialization to make shared fence handle
creation non-fatal when the driver returns E_NOTIMPL.

On native Windows, CreateSharedHandle succeeds and behavior is unchanged.
On Wine/vkd3d, CreateSharedHandle on fences returns E_NOTIMPL (unimplemented
in vkd3d-proton). Without this patch Dawn fails RequestDevice entirely.
With this patch the same binary runs on both Wine and native Windows.

Target: third_party/externals/dawn/src/dawn/native/d3d12/SharedFenceD3D12.cpp
  (In Skia m144 the call was in DeviceD3D12.cpp; from m149 it moved here.)
"""

import sys
import re
from pathlib import Path


def apply_patches(skia_dir: Path):
    # m149+: CreateSharedHandle moved to SharedFenceD3D12.cpp
    target = (
        skia_dir
        / "third_party" / "externals" / "dawn"
        / "src" / "dawn" / "native" / "d3d12"
        / "SharedFenceD3D12.cpp"
    )
    # m144 fallback
    target_legacy = (
        skia_dir
        / "third_party" / "externals" / "dawn"
        / "src" / "dawn" / "native" / "d3d12"
        / "DeviceD3D12.cpp"
    )

    if target.exists():
        _patch_shared_fence(target)
    elif target_legacy.exists():
        _patch_device_legacy(target_legacy)
    else:
        print("  WARNING: Neither SharedFenceD3D12.cpp nor DeviceD3D12.cpp found, skipping fence handle patch")


def _patch_shared_fence(target: Path):
    """Patch for Skia m149+: CreateSharedHandle is in SharedFenceD3D12.cpp,
    spanning multiple lines inside a DAWN_TRY block."""
    content = target.read_text(encoding="utf-8")

    # Idempotency guard
    if "fenceHandleHr" in content:
        print("  SharedFenceD3D12.cpp: fence handle patch already applied, skipping.")
        return

    # Match the multi-line DAWN_TRY block that calls CreateSharedHandle.
    # The block looks like (with 4-space indent):
    #     DAWN_TRY(
    #         CheckHRESULT(device->GetD3D12Device()->CreateSharedHandle(
    #                          d3d12Fence.Get(), nullptr, GENERIC_ALL, nullptr, ownedHandle.GetMut()),
    #                      "D3D12 create fence handle"));
    #     DAWN_ASSERT(ownedHandle.IsValid());
    #
    # Use re.DOTALL so '.' matches newlines; .*? is non-greedy so we stop at
    # the first "D3D12 create fence handle" occurrence.
    pattern = re.compile(
        r'( +)DAWN_TRY\(.*?"D3D12 create fence handle"\)\);\s*\n'
        r'\s+DAWN_ASSERT\(ownedHandle\.IsValid\(\)\);',
        re.DOTALL,
    )

    m = pattern.search(content)
    if not m or "CreateSharedHandle" not in m.group(0):
        print("  WARNING: Could not locate the multi-line DAWN_TRY CreateSharedHandle block "
              "in SharedFenceD3D12.cpp — Dawn version may have changed. Skipping.")
        return

    indent = m.group(1)
    replacement = (
        f"{indent}// CreateSharedHandle may fail with E_NOTIMPL on drivers that do not support\n"
        f"{indent}// shared fence handles (e.g. Wine/vkd3d-proton). Tolerate this so that basic\n"
        f"{indent}// GPU rendering continues to work; fence interop/export will be unavailable.\n"
        f"{indent}{{\n"
        f"{indent}    HRESULT fenceHandleHr = device->GetD3D12Device()->CreateSharedHandle(\n"
        f"{indent}        d3d12Fence.Get(), nullptr, GENERIC_ALL, nullptr, ownedHandle.GetMut());\n"
        f"{indent}    if (FAILED(fenceHandleHr) && fenceHandleHr != E_NOTIMPL) {{\n"
        f"{indent}        DAWN_TRY(CheckHRESULT(fenceHandleHr, \"D3D12 create fence handle\"));\n"
        f"{indent}    }}\n"
        f"{indent}}}"
    )

    patched = pattern.sub(replacement, content, count=1)
    target.write_text(patched, encoding="utf-8")
    print("  Patched SharedFenceD3D12.cpp: shared fence handle creation is now non-fatal (E_NOTIMPL tolerated)")


def _patch_device_legacy(target: Path):
    """Patch for Skia m144: CreateSharedHandle is in DeviceD3D12.cpp on a single line."""
    content = target.read_text(encoding="utf-8")

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
                new_lines.append(pad + "  if (FAILED(fenceHandleHr) && fenceHandleHr != E_NOTIMPL) {\n")
                new_lines.append(pad + '    DAWN_TRY(CheckHRESULT(fenceHandleHr, "D3D12 create fence handle"));\n')
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
