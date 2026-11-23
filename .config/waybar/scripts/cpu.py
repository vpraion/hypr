#!/usr/bin/env python3
"""Waybar module: CPU usage, frequency, and RAM usage."""

import glob
import json
import pathlib

STATE_FILE = pathlib.Path("/tmp/waybar-cpu.state")


def read_cpu_usage() -> float:
    with open("/proc/stat", "r", encoding="utf-8") as f:
        parts = f.readline().split()
    vals = [int(x) for x in parts[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    total = sum(vals)

    prev_total, prev_idle = 0, 0
    if STATE_FILE.exists():
        try:
            prev_total, prev_idle = map(int, STATE_FILE.read_text().split())
        except ValueError:
            pass

    STATE_FILE.write_text(f"{total} {idle}")
    d_total = total - prev_total
    d_idle = idle - prev_idle
    if prev_total == 0 or d_total <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (d_total - d_idle) / d_total))


def read_cpu_freq_ghz() -> float:
    freqs = []
    for path in glob.glob("/sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq"):
        try:
            freqs.append(int(pathlib.Path(path).read_text().strip()) / 1_000_000.0)
        except OSError:
            pass
    if freqs:
        return sum(freqs) / len(freqs)

    mhz = []
    with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("cpu MHz"):
                mhz.append(float(line.split(":", 1)[1].strip()) / 1000.0)
    return sum(mhz) / len(mhz) if mhz else 0.0


def read_cpu_name() -> str:
    with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return "CPU"


def read_cpu_temp_c() -> float | None:
    for name_file in glob.glob("/sys/class/hwmon/hwmon*/name"):
        try:
            name = pathlib.Path(name_file).read_text().strip()
        except OSError:
            continue
        if name in ("zenpower", "k10temp", "coretemp"):
            temp_file = pathlib.Path(name_file).parent / "temp1_input"
            try:
                return int(temp_file.read_text().strip()) / 1000.0
            except OSError:
                pass
    return None


def read_ram_gib() -> tuple[float, float]:
    info = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as f:
        for line in f:
            key, val = line.split(":", 1)
            info[key] = int(val.strip().split()[0])
    total_kib = info.get("MemTotal", 0)
    avail_kib = info.get("MemAvailable", 0)
    used_gib = (total_kib - avail_kib) / (1024 * 1024)
    total_gib = total_kib / (1024 * 1024)
    return used_gib, total_gib


def main() -> None:
    name = read_cpu_name()
    usage = read_cpu_usage()
    freq = read_cpu_freq_ghz()
    temp = read_cpu_temp_c()
    ram_used, ram_total = read_ram_gib()

    temp_str = f"{temp:.0f}°C" if temp is not None else "--°C"
    text = f"  {usage:.0f}% {freq:.1f}GHz {temp_str} · {ram_used:.1f}G"
    tooltip = (
        f"{name}\n"
        f"Usage: {usage:.1f}% @ {freq:.2f} GHz ({temp_str})\n"
        f"RAM: {ram_used:.1f} / {ram_total:.1f} GiB"
    )
    print(json.dumps({"text": text, "tooltip": tooltip}))


if __name__ == "__main__":
    main()
