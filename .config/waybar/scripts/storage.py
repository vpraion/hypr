#!/usr/bin/env python3
"""Waybar module: Storage read and write speed."""

import json
import os
import pathlib
import subprocess
import sys
import time

SIGNAL_NUM = 12
RUNTIME_DIR = pathlib.Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
STATE_FILE = RUNTIME_DIR / "waybar-storage.state"
SELECT_FILE = RUNTIME_DIR / "waybar-storage-selected"
IGNORE_PREFIXES = ("loop", "ram", "zram", "dm-", "sr")
SECTOR_SIZE = 512


def fmt_rate(bytes_per_sec: float) -> str:
    if bytes_per_sec < 1024:
        return f"{bytes_per_sec:.0f}B"
    if bytes_per_sec < 1024 ** 2:
        return f"{bytes_per_sec / 1024:.0f}K"
    if bytes_per_sec < 1024 ** 3:
        return f"{bytes_per_sec / (1024 ** 2):.1f}M"
    return f"{bytes_per_sec / (1024 ** 3):.1f}G"


def list_disks() -> list[str]:
    return sorted(
        d for d in os.listdir("/sys/block") if not d.startswith(IGNORE_PREFIXES)
    )


def disk_label(dev: str) -> str:
    """Return disk device name with its hardware model if available."""
    model_path = pathlib.Path("/sys/block") / dev / "device" / "model"
    try:
        model = model_path.read_text(encoding="utf-8").strip()
        if model:
            return f"{dev} ({model})"
    except OSError:
        pass
    return dev


def get_selected(disks: list[str]) -> str:
    try:
        sel = SELECT_FILE.read_text(encoding="utf-8").strip()
        if sel in disks:
            return sel
    except OSError:
        pass
    return "all"


def cycle_selection() -> None:
    disks = list_disks()
    options = ["all"] + disks
    current = get_selected(disks)
    nxt = options[(options.index(current) + 1) % len(options)]

    tmp = SELECT_FILE.with_name(f"{SELECT_FILE.name}.tmp.{os.getpid()}")
    tmp.write_text(nxt, encoding="utf-8")
    os.replace(tmp, SELECT_FILE)
    try:
        STATE_FILE.unlink()
    except FileNotFoundError:
        pass
    subprocess.run(
        ["pkill", f"-RTMIN+{SIGNAL_NUM}", "waybar"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def read_disk_bytes(target_disks: set[str]) -> tuple[int, int]:
    read_bytes = 0
    write_bytes = 0
    with open("/proc/diskstats", "r", encoding="utf-8") as f:
        for line in f:
            cols = line.split()
            if len(cols) < 10:
                continue
            dev = cols[2]
            if dev in target_disks:
                read_bytes += int(cols[5]) * SECTOR_SIZE
                write_bytes += int(cols[9]) * SECTOR_SIZE
    return read_bytes, write_bytes


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "cycle":
        cycle_selection()
        return

    now = time.monotonic()
    disks = list_disks()
    selected = get_selected(disks)
    target_disks = set(disks) if selected == "all" else {selected}
    selected_label = "All" if selected == "all" else disk_label(selected)
    rd, wr = read_disk_bytes(target_disks)

    prev_t, prev_rd, prev_wr, prev_sel = 0.0, rd, wr, selected
    if STATE_FILE.exists():
        try:
            parts = STATE_FILE.read_text(encoding="utf-8").split()
            if len(parts) == 4:
                prev_t, prev_rd, prev_wr, prev_sel = (
                    float(parts[0]),
                    int(parts[1]),
                    int(parts[2]),
                    parts[3],
                )
        except ValueError:
            pass

    STATE_FILE.write_text(f"{now} {rd} {wr} {selected}", encoding="utf-8")
    dt = now - prev_t
    if prev_t == 0.0 or prev_sel != selected or dt <= 0 or rd < prev_rd or wr < prev_wr:
        rd_rate, wr_rate = 0.0, 0.0
    else:
        rd_rate = (rd - prev_rd) / dt
        wr_rate = (wr - prev_wr) / dt

    menu_lines = [f"{'▸' if selected == 'all' else ' '} All"]
    for dev in disks:
        marker = "▸" if selected == dev else " "
        menu_lines.append(f"{marker} {disk_label(dev)}")

    sel_prefix = "" if selected == "all" else f"{selected} "
    text = f"󰋊  {sel_prefix}R:{fmt_rate(rd_rate)} W:{fmt_rate(wr_rate)}"
    tooltip = (
        f"Selected: {selected_label}\n"
        f"Read: {fmt_rate(rd_rate)}/s\n"
        f"Write: {fmt_rate(wr_rate)}/s\n\n"
        f"Storage (right-click to cycle):\n"
        + "\n".join(menu_lines)
    )
    print(json.dumps({"text": text, "tooltip": tooltip}))


if __name__ == "__main__":
    main()
