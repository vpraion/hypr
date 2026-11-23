#!/usr/bin/env python3
"""Waybar module: Storage read and write speed."""

import json
import os
import pathlib
import time

STATE_FILE = pathlib.Path("/tmp/waybar-storage.state")
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


def read_disk_bytes() -> tuple[int, int, list[str]]:
    disks = {
        d
        for d in os.listdir("/sys/block")
        if not d.startswith(IGNORE_PREFIXES)
    }
    read_bytes = 0
    write_bytes = 0
    with open("/proc/diskstats", "r", encoding="utf-8") as f:
        for line in f:
            cols = line.split()
            if len(cols) < 10:
                continue
            dev = cols[2]
            if dev in disks:
                read_bytes += int(cols[5]) * SECTOR_SIZE
                write_bytes += int(cols[9]) * SECTOR_SIZE
    return read_bytes, write_bytes, sorted(disks)


def main() -> None:
    now = time.monotonic()
    rd, wr, disks = read_disk_bytes()

    prev_t, prev_rd, prev_wr = 0.0, rd, wr
    if STATE_FILE.exists():
        try:
            t_s, rd_s, wr_s = STATE_FILE.read_text().split()
            prev_t, prev_rd, prev_wr = float(t_s), int(rd_s), int(wr_s)
        except ValueError:
            pass

    STATE_FILE.write_text(f"{now} {rd} {wr}")
    dt = now - prev_t
    if prev_t == 0.0 or dt <= 0 or rd < prev_rd or wr < prev_wr:
        rd_rate, wr_rate = 0.0, 0.0
    else:
        rd_rate = (rd - prev_rd) / dt
        wr_rate = (wr - prev_wr) / dt

    text = f"󰋊  R:{fmt_rate(rd_rate)} W:{fmt_rate(wr_rate)}"
    tooltip = (
        f"Disks: {', '.join(disks) if disks else 'none'}\n"
        f"Read: {fmt_rate(rd_rate)}/s\n"
        f"Write: {fmt_rate(wr_rate)}/s"
    )
    print(json.dumps({"text": text, "tooltip": tooltip}))


if __name__ == "__main__":
    main()
