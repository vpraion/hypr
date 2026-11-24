#!/usr/bin/env python3
"""Waybar module: Current media (artist - title) with fixed-slot fallback."""

import html
import json
import subprocess

MAX_LEN = 38


def truncate(text: str, limit: int = MAX_LEN) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def main() -> None:
    try:
        out = subprocess.check_output(
            [
                "playerctl",
                "metadata",
                "--format",
                "{{status}}\t{{artist}}\t{{title}}\t{{playerName}}",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=1,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        print(json.dumps({"text": " ", "tooltip": "No media playing", "class": "empty"}))
        return

    if not out:
        print(json.dumps({"text": " ", "tooltip": "No media playing", "class": "empty"}))
        return

    parts = out.split("\t")
    status = parts[0] if len(parts) > 0 else ""
    artist = parts[1] if len(parts) > 1 else ""
    title = parts[2] if len(parts) > 2 else ""
    player = parts[3] if len(parts) > 3 else "Media"

    if not title and not artist:
        print(json.dumps({"text": " ", "tooltip": "No media playing", "class": "empty"}))
        return

    label = f"{artist} - {title}" if artist and title else (title or artist)
    display = title or artist
    icon = "󰏤" if status.lower() == "paused" else "󰎇"
    text = f"{icon}  {html.escape(truncate(display), quote=False)}"
    tooltip = html.escape(f"Source: {player}\n{label}", quote=False)
    print(json.dumps({"text": text, "tooltip": tooltip}))


if __name__ == "__main__":
    main()
