"""Core logic: detect links, download audio, build the black-screen video.

No Telegram code in here, so it can be tested or reused on its own.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_SIZE = (1280, 720)

PLATFORMS = {
    "Facebook": ("facebook.com", "fb.watch", "fb.com"),
    "Instagram": ("instagram.com", "instagr.am"),
    "X": ("x.com", "twitter.com"),
    "YouTube": ("youtube.com", "youtu.be"),
    "TikTok": ("tiktok.com",),
}

_BARE = r"(?:www\.)?(?:facebook\.com|fb\.watch|instagram\.com|x\.com|twitter\.com)/"
URL_RE = re.compile(rf"(?:https?://|{_BARE})[^\s<>\"']+", re.I)


class ProcessingError(Exception):
    """An error whose message is safe to show to the end user."""


@dataclass
class Link:
    platform: str
    url: str


@dataclass
class MediaInfo:
    width: int | None
    height: int | None
    duration: float | None
    has_audio: bool


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #
def detect_links(text: str) -> list[Link]:
    links: list[Link] = []
    for raw in URL_RE.findall(text or ""):
        url = raw.rstrip(".,;:!?)]}")
        if not url.lower().startswith("http"):
            url = "https://" + url
        host = (urlparse(url).hostname or "").lower()
        platform = "Other"
        for name, domains in PLATFORMS.items():
            if any(host == d or host.endswith("." + d) for d in domains):
                platform = name
                break
        links.append(Link(platform, url))
    return links


# --------------------------------------------------------------------------- #
# Download (blocking - run in a thread)
# --------------------------------------------------------------------------- #
def download_audio(
    url: str,
    dest_dir: Path,
    cookies_file: str | None = None,
    cookies_browser: str | None = None,
) -> Path:
    import yt_dlp
    from yt_dlp.utils import DownloadError

    opts = {
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "format": "bestaudio/best",  # only the sound is needed
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
    }
    if cookies_file:
        opts["cookiefile"] = cookies_file
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if "entries" in info:
                info = info["entries"][0]
            return Path(ydl.prepare_filename(info))
    except DownloadError as e:
        msg = str(e).splitlines()[-1][:200] if str(e) else "unknown error"
        raise ProcessingError(
            "Couldn't download that link. It may be private, deleted, or need login.\n"
            f"Details: {msg}"
        ) from e


# --------------------------------------------------------------------------- #
# ffmpeg
# --------------------------------------------------------------------------- #
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
    default_size: tuple[int, int] = DEFAULT_SIZE,
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