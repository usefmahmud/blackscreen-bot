"""Download the audio track of a URL with yt-dlp (blocking - run in a thread).

yt_dlp is imported lazily inside download_audio(): it is a heavy dependency
and keeping it out of module scope keeps `python -m bbot` startup fast.
"""

from __future__ import annotations

from pathlib import Path

from bbot.errors import ProcessingError


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
