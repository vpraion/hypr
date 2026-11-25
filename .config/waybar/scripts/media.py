#!/usr/bin/env python3
"""Waybar module: Current media with 16-bar PipeWire mini equalizer visualiser."""

from __future__ import annotations

import html
import json
import math
import os
import select
import signal
import struct
import subprocess
import sys
import threading
import time

# Fits within #custom-media's 540px slot (508px usable ≈ 52 monospace chars at 16px):
# 16 equalizer bars + 2 spaces + 34 title chars = 52 chars (~505px)
NUM_BARS = 16
MAX_LEN = 34

# Audio capture & FFT tuning
SAMPLE_RATE = 16000
FPS = 20
CHUNK_SAMPLES = SAMPLE_RATE // FPS  # 800 samples = 50 ms
CHUNK_BYTES = CHUNK_SAMPLES * 2  # s16le mono
FFT_SIZE = 512  # 32 ms window -> 31.25 Hz bin spacing

BARS = "▁▂▃▄▅▆▇█"

# 16 logarithmic FFT bin slices [lo, hi) covering ~62 Hz to ~7.5 kHz
BAND_SLICES: tuple[tuple[int, int], ...] = (
    (2, 3),      # ~62 Hz
    (3, 4),      # ~94 Hz
    (4, 5),      # ~125 Hz
    (5, 7),      # ~156-188 Hz
    (7, 9),      # ~219-250 Hz
    (9, 12),     # ~281-344 Hz
    (12, 16),    # ~375-469 Hz
    (16, 21),    # ~500-625 Hz
    (21, 28),    # ~656-844 Hz
    (28, 37),    # ~875-1125 Hz
    (37, 50),    # ~1156-1531 Hz
    (50, 67),    # ~1562-2062 Hz
    (67, 90),    # ~2094-2781 Hz
    (90, 122),   # ~2812-3781 Hz
    (122, 168),  # ~3812-5219 Hz
    (168, 240),  # ~5250-7469 Hz
)

# Perceptual tilt weights (compensate for music's ~1/f spectral roll-off)
BAND_WEIGHTS: tuple[float, ...] = tuple(
    (((lo + hi) * 0.5 * (SAMPLE_RATE / FFT_SIZE)) / 260.0) ** 0.52
    for lo, hi in BAND_SLICES
)


def _lerp_hex(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> str:
    r = round(c1[0] + (c2[0] - c1[0]) * t)
    g = round(c1[1] + (c2[1] - c1[1]) * t)
    b = round(c1[2] + (c2[2] - c1[2]) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _build_gradient(stops: tuple[tuple[int, int, int], ...], count: int) -> tuple[str, ...]:
    colors: list[str] = []
    segs = len(stops) - 1
    for i in range(count):
        pos = (i / (count - 1)) * segs if count > 1 else 0.0
        idx = min(segs - 1, int(pos))
        colors.append(_lerp_hex(stops[idx], stops[idx + 1], pos - idx))
    return tuple(colors)


# Tokyo Night gradient: @hypr-cyan -> @cyan -> @blue -> @purple
BAR_COLORS: tuple[str, ...] = _build_gradient(
    ((0x33, 0xCC, 0xFF), (0x7D, 0xCF, 0xFF), (0x7A, 0xA2, 0xF7), (0xBB, 0x9A, 0xF7)),
    NUM_BARS,
)

# Precomputed Hann window and radix-2 FFT tables
HANN: tuple[float, ...] = tuple(
    0.5 * (1.0 - math.cos(2.0 * math.pi * i / (FFT_SIZE - 1)))
    for i in range(FFT_SIZE)
)
_FFT_BITS = FFT_SIZE.bit_length() - 1
_BIT_REV: tuple[int, ...] = tuple(
    int(f"{i:0{_FFT_BITS}b}"[::-1], 2) for i in range(FFT_SIZE)
)
_TWIDDLES: tuple[tuple[int, int, tuple[tuple[float, float], ...]], ...] = tuple(
    (
        size,
        size // 2,
        tuple(
            (math.cos(-2.0 * math.pi * k / size), math.sin(-2.0 * math.pi * k / size))
            for k in range(size // 2)
        ),
    )
    for size in (1 << s for s in range(1, _FFT_BITS + 1))
)


def fft_magnitudes(samples: tuple[int, ...], offset: int) -> list[float]:
    """Compute magnitude spectrum (bins 0..FFT_SIZE/2-1) via pure-Python radix-2 FFT."""
    hann = HANN
    re = [samples[offset + r] * hann[r] for r in _BIT_REV]
    im = [0.0] * FFT_SIZE
    n = FFT_SIZE
    for size, half, tw in _TWIDDLES:
        for start in range(0, n, size):
            for k in range(half):
                wr, wi = tw[k]
                i = start + k
                j = i + half
                rj = re[j]
                ij = im[j]
                tr = wr * rj - wi * ij
                ti = wr * ij + wi * rj
                ri = re[i]
                ii = im[i]
                re[j] = ri - tr
                im[j] = ii - ti
                re[i] = ri + tr
                im[i] = ii + ti
    hypot = math.hypot
    inv_n = 1.0 / n
    return [hypot(re[k], im[k]) * inv_n for k in range(n // 2)]


def truncate(text: str, limit: int = MAX_LEN) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def query_media() -> tuple[str, str, str, str]:
    """Query active player metadata via playerctl."""
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
        return ("", "", "", "")

    if not out:
        return ("", "", "", "")

    parts = out.split("\t")
    status = parts[0] if len(parts) > 0 else ""
    artist = parts[1] if len(parts) > 1 else ""
    title = parts[2] if len(parts) > 2 else ""
    player = parts[3] if len(parts) > 3 else "Media"
    return (status, artist, title, player)


class MediaState:
    """Thread-safe container for current media state, updated via playerctl -F."""

    def __init__(self, stop_event: threading.Event) -> None:
        self._lock = threading.Lock()
        self._stop = stop_event
        self.changed = threading.Event()
        self._state: tuple[str, str, str, str] = query_media()
        self._follow_proc: subprocess.Popen[str] | None = None

    def get(self) -> tuple[str, str, str, str]:
        with self._lock:
            return self._state

    def refresh(self) -> None:
        new_state = query_media()
        with self._lock:
            if new_state != self._state:
                self._state = new_state
                self.changed.set()

    def terminate_follower(self) -> None:
        proc = self._follow_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def _watch_loop(self) -> None:
        while not self._stop.is_set():
            try:
                proc = subprocess.Popen(
                    [
                        "playerctl",
                        "-F",
                        "metadata",
                        "--format",
                        "{{status}}\t{{artist}}\t{{title}}\t{{playerName}}",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                self._follow_proc = proc
            except OSError:
                self._stop.wait(2.0)
                continue

            try:
                assert proc.stdout is not None
                for _ in proc.stdout:
                    if self._stop.is_set():
                        break
                    self.refresh()
            except OSError:
                pass
            finally:
                if proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=1)
                    except (OSError, subprocess.SubprocessError):
                        try:
                            proc.kill()
                        except OSError:
                            pass
                self._follow_proc = None

            if not self._stop.is_set():
                self.refresh()
                self._stop.wait(1.0)

    def start(self) -> None:
        t = threading.Thread(target=self._watch_loop, daemon=True)
        t.start()


def spawn_pw_cat() -> subprocess.Popen[bytes] | None:
    try:
        return subprocess.Popen(
            [
                "pw-cat",
                "--record",
                "--raw",
                "--rate",
                str(SAMPLE_RATE),
                "--channels",
                "1",
                "--format",
                "s16",
                "--latency",
                "40ms",
                "-P",
                "stream.capture.sink=true node.passive=true media.name=waybar-media-eq node.name=waybar-media-eq",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None


def stop_proc(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=1)
        except (OSError, subprocess.SubprocessError):
            try:
                proc.kill()
            except OSError:
                pass


def render_eq(levels: list[float]) -> str:
    max_idx = len(BARS) - 1
    scale = len(BARS) - 0.01
    return "".join(
        f"<span color='{color}'>{BARS[min(max_idx, max(0, int(level * scale)))]}</span>"
        for color, level in zip(BAR_COLORS, levels)
    )


def emit(payload: dict[str, str], last_line: list[str]) -> bool:
    line = json.dumps(payload, ensure_ascii=False)
    if line == last_line[0]:
        return True
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        last_line[0] = line
        return True
    except BrokenPipeError:
        return False


def main() -> None:
    stop_event = threading.Event()
    media = MediaState(stop_event)
    pw_proc: subprocess.Popen[bytes] | None = None

    def handle_signal(_signum: int, _frame: object) -> None:
        stop_event.set()
        media.changed.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    media.start()

    smooth = [0.0] * NUM_BARS
    agc = 90.0
    buf = bytearray()
    last_line = [""]
    last_refresh = time.monotonic()
    last_audio_ts = time.monotonic()
    frame_interval = 1.0 / FPS
    next_frame_ts = time.monotonic()

    try:
        while not stop_event.is_set():
            now = time.monotonic()
            if now - last_refresh >= 2.0:
                media.refresh()
                last_refresh = now

            status, artist, title, player = media.get()
            has_media = bool(title or artist)
            is_playing = has_media and status.lower() == "playing"

            if not has_media:
                stop_proc(pw_proc)
                pw_proc = None
                buf.clear()
                smooth = [0.0] * NUM_BARS
                if not emit(
                    {"text": " ", "tooltip": "No media playing", "class": "empty"},
                    last_line,
                ):
                    break
                media.changed.wait(timeout=2.0)
                media.changed.clear()
                continue

            label = f"{artist} - {title}" if artist and title else (title or artist)
            display = html.escape(truncate(title or artist), quote=False)
            tooltip = html.escape(f"Source: {player}\n{label}", quote=False)

            if not is_playing:
                stop_proc(pw_proc)
                pw_proc = None
                buf.clear()
                smooth = [0.0] * NUM_BARS
                if not emit(
                    {
                        "text": f"󰏤  {display}",
                        "tooltip": tooltip,
                        "class": "paused",
                    },
                    last_line,
                ):
                    break
                media.changed.wait(timeout=2.0)
                media.changed.clear()
                continue

            if pw_proc is None or pw_proc.poll() is not None:
                stop_proc(pw_proc)
                buf.clear()
                pw_proc = spawn_pw_cat()
                if pw_proc is None or pw_proc.stdout is None:
                    if not emit(
                        {"text": f"󰎇  {display}", "tooltip": tooltip, "class": "playing"},
                        last_line,
                    ):
                        break
                    media.changed.wait(timeout=1.0)
                    media.changed.clear()
                    continue
                last_audio_ts = time.monotonic()
                next_frame_ts = last_audio_ts
                if not emit(
                    {
                        "text": f"{render_eq(smooth)}  {display}",
                        "tooltip": tooltip,
                        "class": "playing",
                    },
                    last_line,
                ):
                    break

            fd = pw_proc.stdout.fileno()
            # Pace playback smoothly across pw-cat's 4 KB pipe bursts
            wait_s = max(0.0, next_frame_ts - time.monotonic()) if len(buf) >= CHUNK_BYTES else 0.05
            ready, _, _ = select.select([fd], [], [], wait_s)

            if media.changed.is_set():
                media.changed.clear()
                continue

            if ready:
                try:
                    data = os.read(fd, 8192)
                except OSError:
                    data = b""

                if not data:
                    stop_proc(pw_proc)
                    pw_proc = None
                    buf.clear()
                    time.sleep(0.25)
                    continue

                buf.extend(data)
                last_audio_ts = time.monotonic()
                # Bound queued backlog to <= 4 frames (~200 ms) so latency stays tight
                max_buf = CHUNK_BYTES * 4
                if len(buf) > max_buf:
                    del buf[: len(buf) - max_buf]

            now = time.monotonic()
            if len(buf) >= CHUNK_BYTES:
                if now < next_frame_ts:
                    continue
                chunk = bytes(buf[:CHUNK_BYTES])
                del buf[:CHUNK_BYTES]
                next_frame_ts = now + frame_interval

                samples = struct.unpack(f"<{CHUNK_SAMPLES}h", chunk)
                sq_sum = 0
                for s in samples[::4]:
                    sq_sum += s * s
                rms = math.sqrt(sq_sum / (CHUNK_SAMPLES // 4))

                if rms < 8.0:
                    targets = [0.0] * NUM_BARS
                    agc = max(14.0, agc * 0.99)
                else:
                    spectrum = fft_magnitudes(samples, CHUNK_SAMPLES - FFT_SIZE)
                    bands = []
                    for (lo, hi), weight in zip(BAND_SLICES, BAND_WEIGHTS):
                        # Blend RMS and peak in each band so transients pop without jitter
                        band_bins = spectrum[lo:hi]
                        band_rms = math.sqrt(sum(v * v for v in band_bins) / len(band_bins))
                        band_peak = max(band_bins)
                        bands.append((band_rms * 0.65 + band_peak * 0.35) * weight)

                    peak = max(bands)
                    if peak > agc:
                        agc = agc * 0.65 + peak * 0.35
                    else:
                        agc = max(14.0, agc * 0.988)

                    targets = [
                        min(1.0, (b / agc) ** 0.72) if b > 1.2 else 0.0
                        for b in bands
                    ]

                for i, target in enumerate(targets):
                    if target > smooth[i]:
                        smooth[i] = smooth[i] * 0.28 + target * 0.72
                    else:
                        smooth[i] = max(0.0, smooth[i] * 0.72 + target * 0.28 - 0.015)
            elif now - last_audio_ts >= 0.25:
                # Sink is genuinely silent/corked: smoothly decay bars to zero
                for i in range(NUM_BARS):
                    smooth[i] = max(0.0, smooth[i] * 0.72 - 0.02)
            else:
                continue

            if not emit(
                {
                    "text": f"{render_eq(smooth)}  {display}",
                    "tooltip": tooltip,
                    "class": "playing",
                },
                last_line,
            ):
                break
    finally:
        stop_event.set()
        stop_proc(pw_proc)
        media.terminate_follower()


if __name__ == "__main__":
    main()
