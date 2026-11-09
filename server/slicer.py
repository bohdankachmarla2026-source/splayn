"""Slice a model with Bambu Studio CLI and read weight and print time from its result.

Usage:
    python3 slicer.py model.stl pla standard

Bambu Studio writes result.json next to the G-code. It holds the filament weight
(total_used_g) and the print time (main_predication, in seconds).
"""
from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass

SLICER_BIN = "/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"
PROFILE_ROOT = "/Applications/BambuStudio.app/Contents/Resources/profiles"
PROFILE_DIR = os.path.join(PROFILE_ROOT, "BBL")
MACHINE_PROFILE = "Bambu Lab P1S 0.4 nozzle"
# Build volume of the printer, shown to customers. P1S: 256 x 256 x 250 mm.
BUILD_VOLUME_MM = (256, 256, 250)
TIMEOUT_SEC = 300

_index: dict[str, str] | None = None


def _profile_index() -> dict[str, str]:
    """Map profile name -> file path for every bundled profile (needed to resolve inheritance)."""
    global _index
    if _index is None:
        _index = {}
        for root, _, files in os.walk(PROFILE_ROOT):
            for f in files:
                if f.endswith(".json"):
                    _index.setdefault(f[:-5], os.path.join(root, f))
    return _index


def resolve_profile(name: str) -> dict:
    """Load a profile and merge the parents it inherits from.

    Bambu Studio's CLI does not resolve `inherits` for a single file, so values such as
    layer height or filament density would be missing without this step.
    """
    data = json.load(open(_profile_index()[name], encoding="utf-8"))
    parent = data.get("inherits")
    if not parent:
        return data
    merged = resolve_profile(parent)
    merged.update(data)
    merged.pop("inherits", None)
    return merged


# Textured PEI is the A1 default plate. PETG fails with the Cool Plate setting (error -61).
BED_TYPE = "Textured PEI Plate"


def _write_profile(name: str, dest_dir: str, filename: str, extra: dict | None = None) -> str:
    path = os.path.join(dest_dir, filename)
    data = resolve_profile(name)
    data.update(extra or {})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path

# Filament profile per material. Density and speed limits come from the profile itself.
MATERIAL_PROFILES = {
    "pla":  "Bambu PLA Basic @BBL X1C",
    "petg": "Bambu PETG Basic @BBL X1C",
    "abs":  "Bambu ABS @BBL X1C",
}

# Process profile per quality (layer height in brackets). P1S uses the X1C family profiles.
QUALITY_PROFILES = {
    "draft":    "0.28mm Extra Draft @BBL X1C",   # 0.28 mm
    "standard": "0.20mm Standard @BBL X1C",      # 0.20 mm
    "fine":     "0.12mm Fine @BBL X1C",          # 0.12 mm
}

# Supports on, tree type (uses less plastic than normal supports).
SUPPORT_OVERRIDES = {"enable_support": "1", "support_type": "tree(auto)"}


@dataclass
class SliceResult:
    grams: float
    seconds: int


class SliceError(RuntimeError):
    """Slicing failed. `reason` is one of: outside_volume, load_failed, crash, other."""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason


# Bambu Studio return codes seen in result.json.
RETURN_CODE_REASONS = {
    -50: "outside_volume",   # "...no object fully inside [the plate]"
    -6: "load_failed",       # "The input model file ... can not be parsed."
}


def classify(returncode_in_json: int | None, exit_code: int) -> str:
    if returncode_in_json is None:
        # No result file: the process was killed by a signal (negative code) or crashed.
        return "crash" if exit_code < 0 else "other"
    if returncode_in_json == 0:
        return ""
    return RETURN_CODE_REASONS.get(returncode_in_json, "other")


def _read_stl(path: str) -> tuple[bytes, int]:
    """(triangle records in binary STL layout, 50 bytes each; count) from a binary or ASCII STL."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if len(data) == 84 + n * 50:
            return data[84:], n
    # ASCII STL: "vertex x y z" lines, three per facet.
    nums = re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data)
    out = bytearray()
    for i in range(0, len(nums) - 2, 3):
        v = [float(c) for row in nums[i:i + 3] for c in row]
        out += struct.pack("<12fH", 0, 0, 0, *v, 0)
    return bytes(out), len(out) // 50


def _centre_xy(records: bytes, n: int) -> tuple[float, float]:
    """Approximate XY centre of a mesh from a sample of its triangles."""
    xs, ys = [], []
    for i in range(0, n, max(1, n // 300)):
        for k in range(3):
            x, y, _ = struct.unpack_from("<3f", records, i * 50 + 12 + 12 * k)
            xs.append(x)
            ys.append(y)
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


def _write_view(stl_dir: str, dest: str) -> None:
    """Merge the per-object STLs the slicer exported (plate coordinates, mm) into one gzipped STL.

    Objects whose centre is off the build plate (other plates of a 3MF project) are skipped.
    """
    size_x, size_y, _ = BUILD_VOLUME_MM
    blocks, total = [], 0
    for name in sorted(os.listdir(stl_dir)):
        if not name.lower().endswith(".stl"):
            continue
        records, n = _read_stl(os.path.join(stl_dir, name))
        if not n:
            continue
        cx, cy = _centre_xy(records, n)
        if 0 <= cx <= size_x and 0 <= cy <= size_y:
            blocks.append(records)
            total += n
    if not total:
        return
    tmp = dest + ".tmp"
    with gzip.open(tmp, "wb", compresslevel=6) as f:
        f.write(b"view".ljust(80, b" "))
        f.write(struct.pack("<I", total))
        for records in blocks:
            f.write(records)
    os.replace(tmp, dest)


def slice_model(model: str, material: str = "pla", quality: str = "standard",
                slicer_bin: str = SLICER_BIN, view_path: str | None = None) -> SliceResult:
    """Slice one file. With `view_path`, also save the arranged parts as a gzipped STL for the 3D view."""
    if material not in MATERIAL_PROFILES:
        raise ValueError(f"Unknown material: {material}")
    if quality not in QUALITY_PROFILES:
        raise ValueError(f"Unknown quality: {quality}")
    if not os.path.exists(slicer_bin):
        raise FileNotFoundError(f"Slicer not found: {slicer_bin}")

    work = tempfile.mkdtemp(prefix="slice_")
    try:
        out = os.path.join(work, "out")
        os.makedirs(out)
        machine = _write_profile(MACHINE_PROFILE, work, "machine.json")
        process = _write_profile(QUALITY_PROFILES[quality], work, "process.json",
                                 extra=dict(SUPPORT_OVERRIDES, curr_bed_type=BED_TYPE))
        filament = _write_profile(MATERIAL_PROFILES[material], work, "filament.json")
        cmd = [
            # Slice only plate 1. "--slice 0" (all plates) fails on files with an empty extra plate.
            slicer_bin, "--debug", "1", "--slice", "1", "--outputdir", out,
            "--load-settings", f"{machine};{process}",
            "--load-filaments", filament,
            # Auto-place parts on the bed (overlapping or off-bed parts are moved inside it).
            "--arrange", "1", "--ensure-on-bed",
        ]
        if view_path:
            # The same run writes every part, as arranged on the plate, to out/stl/*.stl.
            cmd.append("--export-stl")
        cmd.append(model)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_SEC)

        result_path = os.path.join(out, "result.json")
        code_in_json = None
        error_text = ""
        if os.path.exists(result_path):
            with open(result_path, encoding="utf-8") as f:
                result = json.load(f)
            code_in_json = result.get("return_code")
            error_text = result.get("error_string", "")

        reason = classify(code_in_json, proc.returncode)
        if reason:
            detail = f"exit={proc.returncode} code={code_in_json}: {error_text or proc.stderr[-300:]}"
            raise SliceError(reason, detail)

        plate = result["sliced_plates"][0]
        grams = float(plate["filaments"][0]["total_used_g"])
        seconds = int(round(float(plate["main_predication"])))

        stl_dir = os.path.join(out, "stl")
        if view_path and os.path.isdir(stl_dir):
            try:
                _write_view(stl_dir, view_path)
            except (OSError, struct.error, ValueError):
                pass   # the price is still right; the card just shows no 3D view
        return SliceResult(grams=grams, seconds=seconds)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    r = slice_model(sys.argv[1], sys.argv[2], sys.argv[3])
    print(f"weight_g={r.grams:.2f} time_s={r.seconds}")
