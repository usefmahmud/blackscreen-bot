# Modular Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the flat `bot.py`/`processor.py` scripts into a `blackscreen_bot/` package of small single-responsibility modules with one-way imports, zero import-time side effects, and byte-identical runtime behavior.

**Architecture:** 11-file package. Leaf modules (`config`, `errors`, `models`) hold data/config only; core modules (`links`, `download`, `video`) hold pure processing logic and never import Telegram; the bot layer (`jobs` → `handlers` → `app` → `__main__`) wires everything together. All configuration flows through a frozen `Settings` dataclass passed by parameter — no module-level globals.

**Tech Stack:** Python 3.14 (`.venv/bin/python`), python-telegram-bot 22.8, yt-dlp, python-dotenv, ffmpeg/ffprobe (system).

**Spec:** `docs/superpowers/specs/2026-10-06-modular-refactor-design.md` — the plan argues from the spec; executors read both.

## Global Constraints

- **Behavior identical:** status texts, emoji, and error strings must be byte-for-byte the same as the original `bot.py`/`processor.py` (spec: Data flow).
- **Dependency rule:** `config/errors/models/links/download/video` must never import `telegram` or any bot-layer module; no circular imports (spec: Dependency rule).
- **Zero import-time side effects:** no env reads, no `load_dotenv()`, no `logging.basicConfig`, no semaphore creation at import time — env is read only when `main()` runs (spec: Dependency rule).
- **`DEFAULT_SIZE = (1280, 720)` defined once in `config.py`**; `video.make_black_video` takes `default_size` as a required parameter (spec: config.py / video.py).
- **`import yt_dlp` stays lazy** inside `download_audio()`, documented in the docstring (spec: download.py).
- **Entrypoint:** `python -m blackscreen_bot`. Old `bot.py`, `processor.py`, `main.py` deleted in Task 6 (spec: Target structure).
- **No test suite** — verification = compile / clean-env import / wiring / grep checks only (spec: Verification).
- **No new features, no message-text changes, no `pyproject.toml`, no README changes** (spec: Out of scope).
- Run all commands from the repo root `/Users/usefmahmud/Documents/programming/python/blackscreen-bot` using `.venv/bin/python`.
- Commit after every task. Task 1 initializes git; before that the repo is not under version control.

---

### Task 1: Package skeleton + leaf modules (`config`, `errors`, `models`)

**Files:**
- Create: `.gitignore`
- Create: `blackscreen_bot/__init__.py`
- Create: `blackscreen_bot/errors.py`
- Create: `blackscreen_bot/models.py`
- Create: `blackscreen_bot/config.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces (relied on by all later tasks):
  - `config.DEFAULT_SIZE: tuple[int, int]`
  - `config.Settings` frozen dataclass with fields `bot_token: str`, `allowed_ids: frozenset[int]`, `bot_api_url: str | None`, `cookies_file: str | None`, `cookies_browser: str | None`, `max_duration: float`, `max_parallel: int`, `upload_limit: int`, `default_size: tuple[int, int]`, and classmethod `Settings.from_env() -> Settings`
  - `errors.ProcessingError(Exception)`
  - `models.Link(platform: str, url: str)`, `models.MediaInfo(width: int | None, height: int | None, duration: float | None, has_audio: bool)`

- [ ] **Step 1: Initialize git with a baseline commit**

```bash
printf '.venv/\n__pycache__/\n*.pyc\n.env\n' > .gitignore
git init
git add .gitignore requirements.txt bot.py processor.py main.py docs/
git commit -m "Baseline: existing bot before modular refactor"
```

Expected: `git log` shows one commit.

- [ ] **Step 2: Create package marker**

Create `blackscreen_bot/__init__.py`:

```python
"""blackscreen-bot: turn media and social links into black-screen videos."""
```

- [ ] **Step 3: Create `errors.py`**

Create `blackscreen_bot/errors.py`:

```python
"""Exceptions shared across the package."""

from __future__ import annotations


class ProcessingError(Exception):
    """An error whose message is safe to show to the end user."""
```

- [ ] **Step 4: Create `models.py`**

Create `blackscreen_bot/models.py`:

```python
"""Plain data types shared across the package. No logic in here."""

from __future__ import annotations

from dataclasses import dataclass


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
```

- [ ] **Step 5: Create `config.py`**

Create `blackscreen_bot/config.py`:

```python
"""Configuration: a frozen Settings object built from environment variables.

Importing this module has no side effects - the environment is read only
when Settings.from_env() is called (at startup from app.main()).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_SIZE = (1280, 720)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    allowed_ids: frozenset[int]
    bot_api_url: str | None
    cookies_file: str | None
    cookies_browser: str | None
    max_duration: float  # seconds
    max_parallel: int
    upload_limit: int  # bytes
    default_size: tuple[int, int]

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        try:
            w, h = os.getenv("BLACK_SIZE", "1280x720").lower().split("x")
            default_size = (int(w), int(h))
        except ValueError:
            default_size = DEFAULT_SIZE

        bot_api_url = os.getenv("BOT_API_URL")
        return cls(
            bot_token=os.environ["BOT_TOKEN"],
            allowed_ids=frozenset(
                int(x)
                for x in os.getenv("ALLOWED_USER_IDS", "").replace(" ", "").split(",")
                if x
            ),
            bot_api_url=bot_api_url,
            cookies_file=os.getenv("COOKIES_FILE") or None,
            cookies_browser=os.getenv("COOKIES_FROM_BROWSER") or None,
            max_duration=float(os.getenv("MAX_DURATION_MIN", "90")) * 60,
            max_parallel=int(os.getenv("MAX_PARALLEL_JOBS", "2")),
            upload_limit=(2000 if bot_api_url else 50) * 1024 * 1024,
            default_size=default_size,
        )
```

- [ ] **Step 6: Verify compile + zero side effects**

```bash
.venv/bin/python -m compileall -q blackscreen_bot && echo COMPILE_OK
env -u BOT_TOKEN -u ALLOWED_USER_IDS .venv/bin/python -c "import blackscreen_bot, blackscreen_bot.config, blackscreen_bot.errors, blackscreen_bot.models; print('IMPORT_OK')"
```

Expected: `COMPILE_OK` then `IMPORT_OK`, no other output, exit code 0 (proves no env read at import time).

- [ ] **Step 7: Commit**

```bash
git add blackscreen_bot/ .gitignore
git commit -m "Add package skeleton: config, errors, models"
```

---

### Task 2: Core modules (`links`, `download`, `video`)

**Files:**
- Create: `blackscreen_bot/links.py`
- Create: `blackscreen_bot/download.py`
- Create: `blackscreen_bot/video.py`

**Interfaces:**
- Consumes: `models.Link`, `models.MediaInfo`, `errors.ProcessingError`, `config.DEFAULT_SIZE` (Task 1).
- Produces (relied on by Tasks 3–5):
  - `links.detect_links(text: str) -> list[Link]`
  - `download.download_audio(url: str, dest_dir: Path, cookies_file: str | None = None, cookies_browser: str | None = None) -> Path` — raises `ProcessingError` on failure
  - `video.probe(path: Path) -> MediaInfo`
  - `video.make_black_video(src: Path, out: Path, default_size: tuple[int, int], max_duration: float | None = None) -> MediaInfo` — raises `ProcessingError` on failure

- [ ] **Step 1: Create `links.py`**

Create `blackscreen_bot/links.py`:

```python
"""Detect social-media links in free text and classify their platform."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from blackscreen_bot.models import Link

PLATFORMS = {
    "Facebook": ("facebook.com", "fb.watch", "fb.com"),
    "Instagram": ("instagram.com", "instagr.am"),
    "X": ("x.com", "twitter.com"),
    "YouTube": ("youtube.com", "youtu.be"),
    "TikTok": ("tiktok.com",),
}

_BARE = r"(?:www\.)?(?:facebook\.com|fb\.watch|instagram\.com|x\.com|twitter\.com)/"
URL_RE = re.compile(rf"(?:https?://|{_BARE})[^\s<>\"']+", re.I)


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
```

- [ ] **Step 2: Create `download.py`**

Create `blackscreen_bot/download.py`:

```python
"""Download the audio track of a URL with yt-dlp (blocking - run in a thread).

yt_dlp is imported lazily inside download_audio(): it is a heavy dependency
and keeping it out of module scope keeps `python -m blackscreen_bot` startup fast.
"""

from __future__ import annotations

from pathlib import Path

from blackscreen_bot.errors import ProcessingError


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
```

- [ ] **Step 3: Create `video.py`**

Create `blackscreen_bot/video.py`:

```python
"""Probe media files and build the black-screen video with ffprobe/ffmpeg.

All functions here are blocking - callers run them in a worker thread.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from blackscreen_bot.errors import ProcessingError
from blackscreen_bot.models import MediaInfo


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
```

- [ ] **Step 4: Verify compile, clean-env import, and link detection smoke check**

```bash
.venv/bin/python -m compileall -q blackscreen_bot && echo COMPILE_OK
env -u BOT_TOKEN -u ALLOWED_USER_IDS .venv/bin/python -c "
import blackscreen_bot.links, blackscreen_bot.download, blackscreen_bot.video
from blackscreen_bot.links import detect_links
found = detect_links('watch https://x.com/foo/status/1 and www.instagram.com/p/abc')
assert [(l.platform, l.url) for l in found] == [
    ('X', 'https://x.com/foo/status/1'),
    ('Instagram', 'https://www.instagram.com/p/abc'),
], found
print('CORE_OK')
"
```

Expected: `COMPILE_OK` then `CORE_OK`.

- [ ] **Step 5: Verify core modules are Telegram-free**

```bash
grep -rnE "^[[:space:]]*(import telegram|from telegram)" blackscreen_bot/config.py blackscreen_bot/errors.py blackscreen_bot/models.py blackscreen_bot/links.py blackscreen_bot/download.py blackscreen_bot/video.py && echo "FAIL: telegram import in core" || echo "CORE_TG_FREE_OK"
```

Expected: `CORE_TG_FREE_OK`.

- [ ] **Step 6: Commit**

```bash
git add blackscreen_bot/
git commit -m "Add core modules: link detection, yt-dlp download, ffmpeg video"
```

---

### Task 3: Job orchestration (`jobs.py`)

**Files:**
- Create: `blackscreen_bot/jobs.py`

**Interfaces:**
- Consumes: `config.Settings`, `errors.ProcessingError`, `video.make_black_video` (Tasks 1–2); Telegram `Message`, `BadRequest`, `ChatAction`.
- Produces (relied on by Tasks 4–5):
  - `jobs.Fetch = Callable[[Path, Message], Awaitable[Path]]` — a callback `(tmp_dir, status_message) -> source_path`
  - `jobs.JobRunner` dataclass with fields `settings: Settings`, `semaphore: asyncio.Semaphore` and method `async run(self, msg: Message, fetch: Fetch) -> None` — handles queueing, temp workspace, conversion, upload, and the full error→status-message mapping.

- [ ] **Step 1: Create `jobs.py`**

Create `blackscreen_bot/jobs.py`:

```python
"""Run one conversion job end to end: queue, fetch, convert, upload.

This is the only module allowed to translate exceptions into user-visible
status messages; the core modules just raise ProcessingError.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from telegram import Message
from telegram.constants import ChatAction
from telegram.error import BadRequest

from blackscreen_bot.config import Settings
from blackscreen_bot.errors import ProcessingError
from blackscreen_bot.video import make_black_video

log = logging.getLogger("blackscreen-bot")

Fetch = Callable[[Path, Message], Awaitable[Path]]


@dataclass
class JobRunner:
    settings: Settings
    semaphore: asyncio.Semaphore

    async def run(self, msg: Message, fetch: Fetch) -> None:
        status = await msg.reply_text("⏳ Queued...", quote=True)
        async with self.semaphore:
            with tempfile.TemporaryDirectory(prefix="bsbot_") as t:
                tmp = Path(t)
                try:
                    src = await fetch(tmp, status)
                    await self._convert_and_send(msg, src, tmp, status)
                except ProcessingError as e:
                    await status.edit_text(f"❌ {e}")
                except BadRequest as e:
                    if "too big" in str(e).lower():
                        await status.edit_text(
                            "❌ That file is too big for me to download "
                            "(20 MB limit on the standard Bot API). Send a link instead."
                        )
                    else:
                        log.exception("Telegram error")
                        await status.edit_text("❌ Telegram rejected the request.")
                except Exception:  # noqa: BLE001
                    log.exception("Unexpected failure")
                    await status.edit_text("❌ Something went wrong. Please try again.")

    async def _convert_and_send(
        self, msg: Message, src: Path, tmp: Path, status: Message
    ) -> None:
        out = tmp / f"black_{src.stem}.mp4"

        await status.edit_text("🎬 Converting...")
        info = await asyncio.to_thread(
            make_black_video, src, out, self.settings.default_size, self.settings.max_duration
        )

        if out.stat().st_size > self.settings.upload_limit:
            raise ProcessingError("The result is larger than Telegram's upload limit.")

        await status.edit_text("📤 Uploading...")
        await msg.chat.send_action(ChatAction.UPLOAD_VIDEO)
        with out.open("rb") as f:
            await msg.reply_video(
                video=f,
                duration=int(info.duration or 0) or None,
                width=info.width,
                height=info.height,
                supports_streaming=True,
                filename=out.name,
                read_timeout=300,
                write_timeout=300,
            )
        await status.delete()
```

- [ ] **Step 2: Verify compile + clean-env import**

```bash
.venv/bin/python -m compileall -q blackscreen_bot && echo COMPILE_OK
env -u BOT_TOKEN -u ALLOWED_USER_IDS .venv/bin/python -c "
import blackscreen_bot.jobs
from blackscreen_bot.jobs import Fetch, JobRunner
import dataclasses, asyncio
fields = {f.name for f in dataclasses.fields(JobRunner)}
assert fields == {'settings', 'semaphore'}, fields
print('JOBS_OK')
"
```

Expected: `COMPILE_OK` then `JOBS_OK`.

- [ ] **Step 3: Commit**

```bash
git add blackscreen_bot/jobs.py
git commit -m "Add JobRunner: queue, convert, upload, error mapping"
```

---

### Task 4: Handlers (`handlers.py`)

**Files:**
- Create: `blackscreen_bot/handlers.py`

**Interfaces:**
- Consumes: `config.Settings`, `jobs.JobRunner`, `jobs.Fetch`, `links.detect_links`, `download.download_audio` (Tasks 1–3).
- Produces (relied on by Task 5):
  - `handlers.authorized(allowed_ids: frozenset[int])` — decorator factory wrapping `(Update, ContextTypes.DEFAULT_TYPE) -> Awaitable[...]`
  - `handlers.Handlers` — `NamedTuple` with fields `start`, `on_media`, `on_text` (each `Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]`)
  - `handlers.create_handlers(settings: Settings, runner: JobRunner) -> Handlers`

- [ ] **Step 1: Create `handlers.py`**

Create `blackscreen_bot/handlers.py`:

```python
"""Telegram update handlers and the authorization decorator.

Every dependency arrives as a parameter - no module-level globals.
"""

from __future__ import annotations

import asyncio
from functools import wraps
from pathlib import Path
from typing import Awaitable, Callable, NamedTuple

from telegram import Message, Update
from telegram.ext import ContextTypes

from blackscreen_bot import download, links
from blackscreen_bot.config import Settings
from blackscreen_bot.jobs import JobRunner

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


class Handlers(NamedTuple):
    start: Handler
    on_media: Handler
    on_text: Handler


def authorized(allowed_ids: frozenset[int]):
    """Gate a handler: reply "private" and drop the update for disallowed users."""

    def decorator(handler: Handler) -> Handler:
        @wraps(handler)
        async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            user = update.effective_user
            if allowed_ids and (not user or user.id not in allowed_ids):
                if update.effective_message:
                    await update.effective_message.reply_text("Sorry, this bot is private.")
                return
            return await handler(update, ctx)

        return wrapper

    return decorator


def create_handlers(settings: Settings, runner: JobRunner) -> Handlers:
    gate = authorized(settings.allowed_ids)

    @gate
    async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "Send me:\n"
            "• a video or audio file\n"
            "• a Facebook / Instagram / X link\n\n"
            "and I'll send back a black-screen video with the same audio."
        )

    @gate
    async def on_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        att = msg.video or msg.audio or msg.voice or msg.video_note or msg.document

        async def fetch(tmp: Path, status: Message) -> Path:
            await status.edit_text("⬇️ Downloading file...")
            tg_file = await att.get_file()
            suffix = Path(tg_file.file_path or "").suffix or ".bin"
            dest = tmp / f"{att.file_unique_id}{suffix}"
            await tg_file.download_to_drive(dest)
            return Path(dest)

        await runner.run(msg, fetch)

    @gate
    async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        found = links.detect_links(msg.text)
        if not found:
            await msg.reply_text(
                "I need a video/audio file or a Facebook / Instagram / X link."
            )
            return

        for link in found:

            async def fetch(tmp: Path, status: Message, link=link) -> Path:
                await status.edit_text(f"⬇️ Downloading from {link.platform}...")
                return await asyncio.to_thread(
                    download.download_audio,
                    link.url,
                    tmp,
                    settings.cookies_file,
                    settings.cookies_browser,
                )

            await runner.run(msg, fetch)

    return Handlers(start, on_media, on_text)
```

- [ ] **Step 2: Verify compile + clean-env import + authorization gate**

```bash
.venv/bin/python -m compileall -q blackscreen_bot && echo COMPILE_OK
env -u BOT_TOKEN -u ALLOWED_USER_IDS .venv/bin/python -c "
import asyncio
from types import SimpleNamespace
import blackscreen_bot.handlers
from blackscreen_bot.handlers import authorized

@authorized(frozenset({1}))
async def sample(update, ctx):
    return 'ok'

blocked = SimpleNamespace(effective_user=SimpleNamespace(id=2), effective_message=None)
allowed = SimpleNamespace(effective_user=SimpleNamespace(id=1), effective_message=None)
assert asyncio.run(sample(blocked, None)) is None
assert asyncio.run(sample(allowed, None)) == 'ok'
print('HANDLERS_OK')
"
```

Expected: `COMPILE_OK` then `HANDLERS_OK`.

- [ ] **Step 3: Commit**

```bash
git add blackscreen_bot/handlers.py
git commit -m "Add handlers: authorized gate, start/media/text handlers"
```

---

### Task 5: Application assembly (`app.py`, `__main__.py`)

**Files:**
- Create: `blackscreen_bot/app.py`
- Create: `blackscreen_bot/__main__.py`

**Interfaces:**
- Consumes: `config.Settings`, `jobs.JobRunner`, `handlers.create_handlers` (Tasks 1–4).
- Produces:
  - `app.build_application(settings: Settings) -> Application` — PTB application with all 3 handlers registered in group 0
  - `app.main() -> None` — load settings, configure logging, warn if open bot, run polling
  - Runnable entrypoint: `python -m blackscreen_bot`

- [ ] **Step 1: Create `app.py`**

Create `blackscreen_bot/app.py`:

```python
"""Assemble the Telegram application and run it.

This is the only module that reads Settings.from_env() and configures logging.
"""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from blackscreen_bot.config import Settings
from blackscreen_bot.handlers import create_handlers
from blackscreen_bot.jobs import JobRunner

log = logging.getLogger("blackscreen-bot")


def build_application(settings: Settings) -> Application:
    builder = Application.builder().token(settings.bot_token)
    if settings.bot_api_url:
        url = settings.bot_api_url
        builder = (
            builder.base_url(f"{url}/bot")
            .base_file_url(f"{url}/file/bot")
            .local_mode(True)
        )
    app = builder.concurrent_updates(True).build()

    runner = JobRunner(
        settings=settings,
        semaphore=asyncio.Semaphore(settings.max_parallel),
    )
    handlers = create_handlers(settings, runner)

    media = (
        filters.VIDEO | filters.AUDIO | filters.VOICE | filters.VIDEO_NOTE
        | filters.Document.VIDEO | filters.Document.AUDIO
    )
    app.add_handler(CommandHandler(["start", "help"], handlers.start))
    app.add_handler(MessageHandler(media, handlers.on_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text))
    return app


def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if not settings.allowed_ids:
        log.warning("ALLOWED_USER_IDS is empty: anyone can use this bot!")
    log.info("Bot started")
    build_application(settings).run_polling(allowed_updates=Update.ALL_TYPES)
```

- [ ] **Step 2: Create `__main__.py`**

Create `blackscreen_bot/__main__.py`:

```python
"""Entry point for `python -m blackscreen_bot`."""

from blackscreen_bot.app import main

main()
```

- [ ] **Step 3: Verify compile + wiring check**

```bash
.venv/bin/python -m compileall -q blackscreen_bot && echo COMPILE_OK
env -u BOT_TOKEN -u ALLOWED_USER_IDS .venv/bin/python -c "
from blackscreen_bot.app import build_application
from blackscreen_bot.config import Settings

settings = Settings(
    bot_token='123:TEST',
    allowed_ids=frozenset({1}),
    bot_api_url=None,
    cookies_file=None,
    cookies_browser=None,
    max_duration=5400.0,
    max_parallel=2,
    upload_limit=50 * 1024 * 1024,
    default_size=(1280, 720),
)
app = build_application(settings)
assert len(app.handlers[0]) == 3, f'expected 3 handlers, got {len(app.handlers[0])}'
print('WIRING_OK')
"
```

Expected: `COMPILE_OK` then `WIRING_OK`.

- [ ] **Step 4: Commit**

```bash
git add blackscreen_bot/app.py blackscreen_bot/__main__.py
git commit -m "Add application assembly and python -m entrypoint"
```

---

### Task 6: Remove old files + full verification

**Files:**
- Delete: `bot.py`
- Delete: `processor.py`
- Delete: `main.py` (empty)

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: final repository state per spec (Target structure): `blackscreen_bot/`, `docs/`, `requirements.txt`, `.gitignore`, `.venv/`.

- [ ] **Step 1: Delete the old flat modules**

```bash
git rm bot.py processor.py main.py
```

- [ ] **Step 2: Full compile + clean-env import of every module (except `__main__`, which launches the bot)**

```bash
.venv/bin/python -m compileall -q blackscreen_bot && echo COMPILE_OK
env -u BOT_TOKEN -u ALLOWED_USER_IDS .venv/bin/python -c "
import blackscreen_bot
import blackscreen_bot.config
import blackscreen_bot.errors
import blackscreen_bot.models
import blackscreen_bot.links
import blackscreen_bot.download
import blackscreen_bot.video
import blackscreen_bot.jobs
import blackscreen_bot.handlers
import blackscreen_bot.app
print('ALL_IMPORTS_OK')
"
```

Expected: `COMPILE_OK` then `ALL_IMPORTS_OK` — proves zero import-time side effects across the whole package.

- [ ] **Step 3: Dependency-rule grep gates**

```bash
grep -rnE "^[[:space:]]*(import telegram|from telegram)" \
  blackscreen_bot/config.py blackscreen_bot/errors.py blackscreen_bot/models.py \
  blackscreen_bot/links.py blackscreen_bot/download.py blackscreen_bot/video.py \
  && echo "FAIL: telegram in core" || echo "GATE1_OK telegram-free core"

grep -rnE "os\.environ|os\.getenv|load_dotenv" blackscreen_bot --include="*.py" \
  | grep -v "^blackscreen_bot/config.py" \
  && echo "FAIL: env access outside config" || echo "GATE2_OK env only in config"

grep -rnE "^[[:space:]]*(import blackscreen_bot\.[a-z_]+|from blackscreen_bot[a-z_. ]*import)" \
  blackscreen_bot/config.py blackscreen_bot/errors.py blackscreen_bot/models.py \
  && echo "FAIL: package imports in leaf modules" || echo "GATE3_OK leaves import nothing in-package"
```

Expected: all three gates print `_OK`. Note: `grep` exits 1 on no match, which is the passing case here (`&&`/`||` handles it).

- [ ] **Step 4: Wires-check — full package end-to-end (build + auth gate)**

```bash
env -u BOT_TOKEN -u ALLOWED_USER_IDS .venv/bin/python -c "
import asyncio
from types import SimpleNamespace

from blackscreen_bot.app import build_application
from blackscreen_bot.config import Settings
from blackscreen_bot.handlers import authorized

settings = Settings(
    bot_token='123:TEST',
    allowed_ids=frozenset({1}),
    bot_api_url=None,
    cookies_file=None,
    cookies_browser=None,
    max_duration=5400.0,
    max_parallel=2,
    upload_limit=50 * 1024 * 1024,
    default_size=(1280, 720),
)
app = build_application(settings)
assert len(app.handlers[0]) == 3, f'expected 3 handlers, got {len(app.handlers[0])}'

@authorized(frozenset({1}))
async def sample(update, ctx):
    return 'ok'

blocked = SimpleNamespace(effective_user=SimpleNamespace(id=2), effective_message=None)
allowed = SimpleNamespace(effective_user=SimpleNamespace(id=1), effective_message=None)
assert asyncio.run(sample(blocked, None)) is None
assert asyncio.run(sample(allowed, None)) == 'ok'
print('FINAL_WIRING_OK')
"
```

Expected: `FINAL_WIRING_OK`.

- [ ] **Step 5: Final structure check + commit**

```bash
ls
git add -A
git commit -m "Remove legacy flat modules; package is now the only source"
git log --oneline
```

Expected: root contains `blackscreen_bot/`, `docs/`, `.gitignore`, `requirements.txt` (plus untracked `.venv/`); `git log` shows 6 commits.
