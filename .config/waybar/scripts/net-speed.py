#!/usr/bin/env python3
"""Waybar module: Network connection status, download speed, and upload speed."""

import json
import os
import pathlib
import subprocess
import sys
import time

SIGNAL_NUM = 11
RUNTIME_DIR = pathlib.Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
STATE_FILE = RUNTIME_DIR / "waybar-net.state"
SELECT_FILE = RUNTIME_DIR / "waybar-net-selected"
IGNORE_PREFIXES = ("lo", "veth", "docker", "br-", "virbr", "tun", "tap")


def fmt_rate(bytes_per_sec: float) -> str:
    if bytes_per_sec < 1024:
        return f"{bytes_per_sec:.0f}B"
    if bytes_per_sec < 1024 ** 2:
        return f"{bytes_per_sec / 1024:.0f}K"
    if bytes_per_sec < 1024 ** 3:
        return f"{bytes_per_sec / (1024 ** 2):.1f}M"
    return f"{bytes_per_sec / (1024 ** 3):.1f}G"


def check_online() -> tuple[bool, str]:
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "CONNECTIVITY", "general"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=1,
        ).strip().lower()
        if out == "full":
            return True, "online (full)"
        if out in ("limited", "portal"):
            return True, f"online ({out})"
        if out == "none":
            return False, "offline"
    except (OSError, subprocess.SubprocessError):
        pass

    # Fallback: check for a default route in /proc/net/route
    try:
        with open("/proc/net/route", "r", encoding="utf-8") as f:
            for line in f.readlines()[1:]:
                cols = line.split()
                if len(cols) >= 2 and not cols[0].startswith(IGNORE_PREFIXES) and cols[1] == "00000000":
                    return True, "online"
    except OSError:
        pass
    return False, "offline"


def iface_label(iface: str) -> str:
    """Return a human-readable label with connection type and link state."""
    net_dir = pathlib.Path("/sys/class/net") / iface
    kind = "Wi-Fi" if (net_dir / "wireless").exists() else "Ethernet"
    try:
        state = (net_dir / "operstate").read_text(encoding="utf-8").strip()
    except OSError:
        state = "unknown"
    return f"{iface} ({kind}, {state})"


def read_net_bytes() -> dict[str, tuple[int, int]]:
    stats: dict[str, tuple[int, int]] = {}
    with open("/proc/net/dev", "r", encoding="utf-8") as f:
        for line in f.readlines()[2:]:
            if ":" not in line:
                continue
            iface, data = line.split(":", 1)
            iface = iface.strip()
            if iface.startswith(IGNORE_PREFIXES):
                continue
            cols = data.split()
            stats[iface] = (int(cols[0]), int(cols[8]))
    return dict(sorted(stats.items()))


def get_selected(ifaces: list[str]) -> str:
    try:
        sel = SELECT_FILE.read_text(encoding="utf-8").strip()
        if sel in ifaces:
            return sel
    except OSError:
        pass
    return "all"


def cycle_selection() -> None:
    ifaces = list(read_net_bytes().keys())
    options = ["all"] + ifaces
    current = get_selected(ifaces)
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


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "cycle":
        cycle_selection()
        return

    now = time.monotonic()
    online, status = check_online()
    stats = read_net_bytes()
    ifaces = list(stats.keys())
    selected = get_selected(ifaces)

    if selected == "all":
        rx = sum(v[0] for v in stats.values())
        tx = sum(v[1] for v in stats.values())
        selected_label = "All"
    else:
        rx, tx = stats[selected]
        selected_label = iface_label(selected)

    prev_t, prev_rx, prev_tx, prev_sel = 0.0, rx, tx, selected
    if STATE_FILE.exists():
        try:
            parts = STATE_FILE.read_text(encoding="utf-8").split()
            if len(parts) == 4:
                prev_t, prev_rx, prev_tx, prev_sel = (
                    float(parts[0]),
                    int(parts[1]),
                    int(parts[2]),
                    parts[3],
                )
        except ValueError:
            pass

    STATE_FILE.write_text(f"{now} {rx} {tx} {selected}", encoding="utf-8")
    dt = now - prev_t
    if prev_t == 0.0 or prev_sel != selected or dt <= 0 or rx < prev_rx or tx < prev_tx:
        rx_rate, tx_rate = 0.0, 0.0
    else:
        rx_rate = (rx - prev_rx) / dt
        tx_rate = (tx - prev_tx) / dt

    sel_prefix = "" if selected == "all" else f"{selected} "
    if not online:
        text = f"󰖪  {sel_prefix}offline"
        css_class = "disconnected"
    else:
        text = f"󰓅  {sel_prefix}↓{fmt_rate(rx_rate)} ↑{fmt_rate(tx_rate)}"
        css_class = "connected"

    menu_lines = [f"{'▸' if selected == 'all' else ' '} All"]
    for iface in ifaces:
        marker = "▸" if selected == iface else " "
        menu_lines.append(f"{marker} {iface_label(iface)}")

    tooltip = (
        f"Status: {status}\n"
        f"Selected: {selected_label}\n"
        f"Download: {fmt_rate(rx_rate)}/s\n"
        f"Upload: {fmt_rate(tx_rate)}/s\n\n"
        f"Network cards (right-click to cycle):\n"
        + "\n".join(menu_lines)
    )
    print(json.dumps({"text": text, "tooltip": tooltip, "class": css_class}))


if __name__ == "__main__":
    main()
