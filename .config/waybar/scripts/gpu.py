#!/usr/bin/env python3
"""Waybar module: AMD GPU (RX 6900 XT) usage, frequency, and VRAM usage."""

import glob
import json
import os
import pathlib


def find_amdgpu_device() -> pathlib.Path | None:
    for card in sorted(glob.glob("/sys/class/drm/card*/device")):
        dev = pathlib.Path(card)
        driver_link = dev / "driver"
        if not driver_link.exists():
            continue
        if os.path.basename(os.path.realpath(driver_link)) == "amdgpu" and (dev / "gpu_busy_percent").exists():
            return dev
    return None


def read_int(path: pathlib.Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except OSError:
        return None


def fmt_freq_hz(hz: int | None) -> str:
    if hz is None:
        return "--"
    mhz = hz / 1_000_000.0
    if mhz >= 1000:
        return f"{mhz / 1000:.1f}GHz"
    return f"{mhz:.0f}MHz"


def main() -> None:
    dev = find_amdgpu_device()
    if dev is None:
        print(json.dumps({"text": "󰢮 --", "tooltip": "AMD GPU not found"}))
        return

    usage = read_int(dev / "gpu_busy_percent")
    vram_used_b = read_int(dev / "mem_info_vram_used")
    vram_total_b = read_int(dev / "mem_info_vram_total")

    hwmon_dirs = glob.glob(str(dev / "hwmon" / "hwmon*"))
    freq_hz = None
    temp_mc = None
    if hwmon_dirs:
        hwmon = pathlib.Path(hwmon_dirs[0])
        freq_hz = read_int(hwmon / "freq1_input")
        temp_mc = read_int(hwmon / "temp1_input")

    usage_str = f"{usage}%" if usage is not None else "--%"
    freq_str = fmt_freq_hz(freq_hz)
    temp_str = f"{temp_mc / 1000:.0f}°C" if temp_mc is not None else "--°C"
    vram_used_gib = (vram_used_b / (1024 ** 3)) if vram_used_b is not None else 0.0
    vram_total_gib = (vram_total_b / (1024 ** 3)) if vram_total_b is not None else 0.0

    text = f"󰢮  {usage_str} {freq_str} {temp_str} · {vram_used_gib:.1f}G"
    tooltip = (
        f"AMD Radeon RX 6900 XT\n"
        f"Usage: {usage_str} @ {freq_str} ({temp_str})\n"
        f"VRAM: {vram_used_gib:.2f} / {vram_total_gib:.1f} GiB"
    )
    print(json.dumps({"text": text, "tooltip": tooltip}))


if __name__ == "__main__":
    main()
