#!/usr/bin/env python3
"""Waybar module: Network connection status, download speed, and upload speed."""

import json
import pathlib
import subprocess
import time

STATE_FILE = pathlib.Path("/tmp/waybar-net.state")
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


def read_net_bytes() -> tuple[int, int, list[str]]:
    rx_total = 0
    tx_total = 0
    ifaces = []
    with open("/proc/net/dev", "r", encoding="utf-8") as f:
        for line in f.readlines()[2:]:
            if ":" not in line:
                continue
            iface, data = line.split(":", 1)
            iface = iface.strip()
            if iface.startswith(IGNORE_PREFIXES):
                continue
            cols = data.split()
            rx = int(cols[0])
            tx = int(cols[8])
            rx_total += rx
            tx_total += tx
            if rx > 0 or tx > 0:
                ifaces.append(iface)
    return rx_total, tx_total, ifaces


def main() -> None:
    now = time.monotonic()
    online, status = check_online()
    rx, tx, ifaces = read_net_bytes()

    prev_t, prev_rx, prev_tx = 0.0, rx, tx
    if STATE_FILE.exists():
        try:
            t_s, rx_s, tx_s = STATE_FILE.read_text().split()
            prev_t, prev_rx, prev_tx = float(t_s), int(rx_s), int(tx_s)
        except ValueError:
            pass

    STATE_FILE.write_text(f"{now} {rx} {tx}")
    dt = now - prev_t
    if prev_t == 0.0 or dt <= 0 or rx < prev_rx or tx < prev_tx:
        rx_rate, tx_rate = 0.0, 0.0
    else:
        rx_rate = (rx - prev_rx) / dt
        tx_rate = (tx - prev_tx) / dt

    iface_list = ", ".join(ifaces) if ifaces else "none"
    if not online:
        text = "󰖪  offline"
        css_class = "disconnected"
    else:
        text = f"󰓅  ↓{fmt_rate(rx_rate)} ↑{fmt_rate(tx_rate)}"
        css_class = "connected"

    tooltip = (
        f"Status: {status}\n"
        f"Interfaces: {iface_list}\n"
        f"Download: {fmt_rate(rx_rate)}/s\n"
        f"Upload: {fmt_rate(tx_rate)}/s"
    )
    print(json.dumps({"text": text, "tooltip": tooltip, "class": css_class}))


if __name__ == "__main__":
    main()
