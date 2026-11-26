#!/usr/bin/env python3
"""Waybar module: CPU usage, frequency, temperature, and RAM usage."""

from __future__ import annotations

import glob
import json
import pathlib
import re
import signal
import sys
import threading

INTERVAL = 2.0
STATE_FILE = pathlib.Path("/tmp/waybar-cpu.state")
HWMON_DRIVERS = ("zenpower", "k10temp", "coretemp")


def read_cpu_stat() -> tuple[int, int]:
    with open("/proc/stat", "r", encoding="utf-8") as f:
        parts = f.readline().split()
    vals = [int(x) for x in parts[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    total = sum(vals)
    return total, idle


def compute_cpu_usage(
    total: int, idle: int, prev_total: int, prev_idle: int
) -> float:
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


def _sensor_index(path: pathlib.Path) -> int:
    m = re.search(r"temp(\d+)_input$", path.name)
    return int(m.group(1)) if m else 0


def discover_temp_sensors() -> list[tuple[str, pathlib.Path]]:
    """Find CPU hwmon temperature inputs as (label, path) pairs."""
    for driver in HWMON_DRIVERS:
        for name_file in sorted(glob.glob("/sys/class/hwmon/hwmon*/name")):
            try:
                name = pathlib.Path(name_file).read_text().strip()
            except OSError:
                continue
            if name != driver:
                continue
            hwmon_dir = pathlib.Path(name_file).parent
            inputs = sorted(hwmon_dir.glob("temp*_input"), key=_sensor_index)
            if not inputs:
                continue
            sensors: list[tuple[str, pathlib.Path]] = []
            for inp in inputs:
                lbl_path = inp.with_name(inp.name.replace("_input", "_label"))
                try:
                    label = lbl_path.read_text().strip()
                except OSError:
                    label = inp.name.replace("_input", "")
                sensors.append((label, inp))
            return sensors
    return []


def read_cpu_temps(
    sensors: list[tuple[str, pathlib.Path]],
) -> tuple[float | None, list[tuple[str, float]]]:
    """Return (primary_temp_c, readings).

    On AMD k10temp/zenpower, prefers the average of Tccd* die sensors over Tctl
    (Tctl is a smoothed SMU fan-control hotspot reading that sits ~15-20°C
    higher than actual core die temperatures at idle).
    """
    readings: list[tuple[str, float]] = []
    for label, path in sensors:
        try:
            readings.append((label, int(path.read_text().strip()) / 1000.0))
        except (OSError, ValueError):
            continue

    if not readings:
        return None, []

    tccds = [val for lbl, val in readings if lbl.startswith("Tccd")]
    if tccds:
        return sum(tccds) / len(tccds), readings

    for prefix in ("Tdie", "Package id", "Tctl"):
        for lbl, val in readings:
            if lbl.startswith(prefix):
                return val, readings

    return readings[0][1], readings


def format_temp_details(readings: list[tuple[str, float]]) -> str:
    ccds = [f"CCD{lbl[4:]} {val:.0f}°C" for lbl, val in readings if lbl.startswith("Tccd")]
    others = [
        f"{lbl} {val:.0f}°C"
        for lbl, val in readings
        if lbl in ("Tdie", "Tctl") or lbl.startswith("Package id")
    ]
    return " · ".join(ccds + others)


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


def build_payload(
    name: str,
    usage: float,
    freq: float,
    temp: float | None,
    readings: list[tuple[str, float]],
    ram_used: float,
    ram_total: float,
) -> dict[str, str]:
    temp_str = f"{temp:.0f}°C" if temp is not None else "--°C"
    text = f"  {usage:.0f}% {freq:.1f}GHz {temp_str} · {ram_used:.1f}G"
    lines = [
        name,
        f"Usage: {usage:.1f}% @ {freq:.2f} GHz ({temp_str})",
    ]
    details = format_temp_details(readings)
    if details and len(readings) > 1:
        lines.append(f"Temps: {details}")
    lines.append(f"RAM: {ram_used:.1f} / {ram_total:.1f} GiB")
    return {"text": text, "tooltip": "\n".join(lines)}


def run_once() -> None:
    name = read_cpu_name()
    total, idle = read_cpu_stat()
    prev_total, prev_idle = 0, 0
    if STATE_FILE.exists():
        try:
            prev_total, prev_idle = map(int, STATE_FILE.read_text().split())
        except ValueError:
            pass
    STATE_FILE.write_text(f"{total} {idle}")
    usage = compute_cpu_usage(total, idle, prev_total, prev_idle)
    freq = read_cpu_freq_ghz()
    sensors = discover_temp_sensors()
    temp, readings = read_cpu_temps(sensors)
    ram_used, ram_total = read_ram_gib()
    print(json.dumps(build_payload(name, usage, freq, temp, readings, ram_used, ram_total)))


def main() -> None:
    if "--once" in sys.argv[1:]:
        run_once()
        return

    stop_event = threading.Event()

    def handle_signal(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    name = read_cpu_name()
    sensors = discover_temp_sensors()
    prev_total, prev_idle = read_cpu_stat()
    if stop_event.wait(0.25):
        return

    while not stop_event.is_set():
        total, idle = read_cpu_stat()
        usage = compute_cpu_usage(total, idle, prev_total, prev_idle)
        prev_total, prev_idle = total, idle

        freq = read_cpu_freq_ghz()
        temp, readings = read_cpu_temps(sensors)
        if temp is None:
            sensors = discover_temp_sensors()
            temp, readings = read_cpu_temps(sensors)
        ram_used, ram_total = read_ram_gib()

        payload = build_payload(name, usage, freq, temp, readings, ram_used, ram_total)
        try:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except BrokenPipeError:
            break

        stop_event.wait(INTERVAL)


if __name__ == "__main__":
    main()
