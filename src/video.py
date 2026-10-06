"""Probe media files and build the black-screen video with ffprobe/ffmpeg.

All functions here are blocking - callers run them in a worker thread.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from src.errors import ProcessingError
from src.models import MediaInfo


def probe(path: Path) -> MediaInfo:
    p = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,codec_name,width,height:format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        data = {}

    width = height = None
    has_audio = False
    for s in data.get("streams", []):
        if s.get("codec_type") == "audio":
            has_audio = True
        elif (
            s.get("codec_type") == "video"
            and width is None
            and s.get("codec_name") not in ("mjpeg", "png")  # skip cover art
            and s.get("width")
        ):
            width, height = int(s["width"]), int(s["height"])

    try:
        duration = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    return MediaInfo(width, height, duration, has_audio)


def make_black_video(
    src: Path,
    out: Path,
    default_size: tuple[int, int],
    max_duration: float | None = None,
) -> MediaInfo:
    """Blocking. Returns info about the produced video."""
    info = probe(src)
    if not info.has_audio:
        raise ProcessingError("I couldn't find any audio in that file.")
    if max_duration and info.duration and info.duration > max_duration:
        raise ProcessingError(
            f"That's too long ({info.duration / 60:.0f} min). "
            f"The limit is {max_duration / 60:.0f} min."
        )

    w, h = (info.width, info.height) if info.width else default_size
    w, h = w - w % 2, h - h % 2  # libx264 needs even dimensions

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r=25",
        "-i", str(src),
        "-map", "0:v", "-map", "1:a:0",
        "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast",
        "-crf", "35", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-movflags", "+faststart",
        str(out),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise ProcessingError(f"Conversion failed: {p.stderr.strip()[-200:]}")
    return MediaInfo(w, h, info.duration, True)
