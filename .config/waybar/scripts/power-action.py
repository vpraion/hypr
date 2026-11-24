#!/usr/bin/env python3
"""Two-step confirmation handler for Waybar power menu actions."""

import json
import os
import subprocess
import sys
import time

CONFIRM_TIMEOUT = 5.0
SIGNAL_NUM = 10
STATE_FILE = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
    "waybar-power-confirm.json",
)

ACTIONS = {
    "power": {
        "label": "Shutdown",
        "icon": "⏻",
        "cmd": ["systemctl", "poweroff"],
    },
    "reboot": {
        "label": "Reboot",
        "icon": "󰜉",
        "cmd": ["systemctl", "reboot"],
    },
    "logout": {
        "label": "Logout",
        "icon": "󰍃",
        "cmd": ["hyprctl", "-q", "dispatch", "hl.dsp.exit()"],
    },
    "suspend": {
        "label": "Suspend",
        "icon": "󰤄",
        "cmd": ["systemctl", "suspend"],
    },
}


def read_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def write_state(data):
    tmp = f"{STATE_FILE}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, STATE_FILE)


def clear_state():
    try:
        os.remove(STATE_FILE)
    except FileNotFoundError:
        pass


def signal_waybar():
    subprocess.run(
        ["pkill", f"-RTMIN+{SIGNAL_NUM}", "waybar"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def cmd_status(action):
    info = ACTIONS[action]
    state = read_state()
    is_armed = (
        state.get("action") == action
        and state.get("expires", 0) > time.time()
    )
    if is_armed:
        payload = {
            "text": f"{info['icon']}?",
            "tooltip": f"Click again within {int(CONFIRM_TIMEOUT)}s to confirm {info['label']}\nRight-click to cancel",
            "class": "confirming",
        }
    else:
        payload = {
            "text": info["icon"],
            "tooltip": info["label"],
            "class": "normal",
        }
    print(json.dumps(payload), flush=True)


def cmd_click(action):
    info = ACTIONS[action]
    state = read_state()
    is_armed = (
        state.get("action") == action
        and state.get("expires", 0) > time.time()
    )
    if is_armed:
        clear_state()
        signal_waybar()
        subprocess.Popen(
            info["cmd"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return

    token = f"{time.time():.6f}-{os.getpid()}"
    write_state(
        {
            "action": action,
            "expires": time.time() + CONFIRM_TIMEOUT,
            "token": token,
        }
    )
    signal_waybar()
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "expire", token],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def cmd_expire(token):
    time.sleep(CONFIRM_TIMEOUT + 0.1)
    state = read_state()
    if state.get("token") == token:
        clear_state()
        signal_waybar()


def cmd_cancel():
    clear_state()
    signal_waybar()


def main():
    if len(sys.argv) < 2:
        sys.exit(1)

    subcmd = sys.argv[1]
    if subcmd == "status" and len(sys.argv) == 3 and sys.argv[2] in ACTIONS:
        cmd_status(sys.argv[2])
    elif subcmd == "click" and len(sys.argv) == 3 and sys.argv[2] in ACTIONS:
        cmd_click(sys.argv[2])
    elif subcmd == "expire" and len(sys.argv) == 3:
        cmd_expire(sys.argv[2])
    elif subcmd == "cancel":
        cmd_cancel()
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
