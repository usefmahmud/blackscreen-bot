# Design: Modular Refactor of blackscreen-bot

**Date:** 2026-10-06
**Status:** Approved (design in chat); pending spec review
**Scope:** Pure structural refactor. No behavior changes, no new features.

## Goal

Restructure the flat scripts (`bot.py` 189 lines, `processor.py` 175 lines, empty `main.py`) into a package with strictly modular architecture: each file small, single-responsibility, unambiguous, with one-way imports and no module-level mutable state.

## Decisions (confirmed with user)

| Decision | Choice |
|---|---|
| Layout | `blackscreen_bot/` package with one-concern submodules |
| Entrypoint | `python -m blackscreen_bot` (root `main.py` deleted) |
| Verification | Import/compile checks only — no test suite added |
| Config | Explicit frozen `Settings` dataclass, passed through signatures; no globals |

## Target structure

```
blackscreen_bot/
  __init__.py      docstring only (package marker, no code)
  __main__.py      calls app.main()
  config.py        Settings frozen dataclass + Settings.from_env()
  errors.py        ProcessingError
  models.py        Link, MediaInfo dataclasses
  links.py         detect_links() — URL regex + platform matching
  download.py      download_audio() — yt-dlp wrapper
  video.py         probe(), make_black_video() — ffprobe/ffmpeg
  jobs.py          JobRunner — semaphore, tempdir, convert+send, error mapping
  handlers.py      authorized() factory + create_handlers()
  app.py           build_application() + main()
```

Root after migration: `blackscreen_bot/`, `docs/`, `requirements.txt`, `.venv/`. Old `bot.py`, `processor.py`, `main.py` are deleted.

## Dependency rule

Imports flow one way:

```
config / errors / models
        ↓
links / download / video          (core: no Telegram imports)
        ↓
jobs                              (Telegram glue)
        ↓
handlers → app → __main__
```

- Core modules (`config`, `errors`, `models`, `links`, `download`, `video`) must never import `telegram` or any bot-layer module.
- No circular imports.
- Importing any module has **zero side effects**: no env reads, no `load_dotenv()`, no logging config, no semaphore creation at import time. Env is read only when `main()` runs.

## Module responsibilities & interfaces

### `config.py`

```python
DEFAULT_SIZE = (1280, 720)

@dataclass(frozen=True)
class Settings:
    bot_token: str
    allowed_ids: frozenset[int]
    bot_api_url: str | None
    cookies_file: str | None
    cookies_browser: str | None
    max_duration: float          # seconds
    max_parallel: int
    upload_limit: int            # bytes
    default_size: tuple[int, int]

    @classmethod
    def from_env(cls) -> Settings: ...
```

- `DEFAULT_SIZE` is defined **once**, here (it is a default configuration value). `config` imports nothing else from the package — it is a leaf module.
- `from_env()` calls `load_dotenv()` first, then reads the same env vars with the same defaults/parse rules as today (`BOT_TOKEN` required via `os.environ[...]`; `ALLOWED_USER_IDS` comma list; `MAX_DURATION_MIN` minutes→seconds; `BLACK_SIZE` `WxH` with fallback to `DEFAULT_SIZE` on `ValueError`; `UPLOAD_LIMIT` 50 MB or 2000 MB when `BOT_API_URL` set).
- Logging setup (`basicConfig`, httpx quieting) lives in `app.main()`, not here — it runs once at startup, not at import.

### `errors.py`

- `class ProcessingError(Exception)` — "message safe to show to the end user". Nothing else.

### `models.py`

- `@dataclass Link: platform: str; url: str`
- `@dataclass MediaInfo: width: int | None; height: int | None; duration: float | None; has_audio: bool`
- No logic.

### `links.py`

- `PLATFORMS` dict, `URL_RE` regex, `detect_links(text: str) -> list[Link]` — moved verbatim from `processor.py` (including trailing-punctuation strip, https:// prefixing, host-suffix platform match, `"Other"` fallback).
- No Telegram imports.

### `download.py`

- `download_audio(url, dest_dir, cookies_file=None, cookies_browser=None) -> Path` — yt-dlp wrapper, moved verbatim. Raises `ProcessingError` with the same user-facing message on `DownloadError`.
- `import yt_dlp` stays **lazy inside the function** (heavy dependency; keeps startup fast). Documented in the module docstring so it reads as intentional.

### `video.py`

- `probe(path: Path) -> MediaInfo` — ffprobe JSON parsing, moved verbatim (cover-art skip, duration parse).
- `make_black_video(src, out, default_size, max_duration=None) -> MediaInfo` — same validation (audio present, duration limit), even-dimension rounding, identical ffmpeg argv, same `ProcessingError` messages.
- `default_size` is a **required parameter** (no module-level default, no import of other package modules): callers always pass `settings.default_size`. `config.DEFAULT_SIZE` is the single source of truth.

### `jobs.py`

- `JobRunner` dataclass: fields `settings: Settings`, `semaphore: asyncio.Semaphore` (created by `app.build_application`, not at import).
- `async def run(self, msg: Message, fetch: Callable[[Path, Message], Awaitable[Path]]) -> None` — merges current `run_job` + `convert_and_send`:
  1. reply "⏳ Queued...", acquire semaphore, create tempdir `bsbot_`
  2. `src = await fetch(tmp, status)`
  3. status "🎬 Converting..." → `asyncio.to_thread(make_black_video, ...)` → size check vs `settings.upload_limit` → status "📤 Uploading..." → `reply_video(...)` (same kwargs) → delete status
  4. Error mapping, same messages as today: `ProcessingError` → `❌ {e}`; `BadRequest` containing "too big" → the 20 MB download-limit message; other `BadRequest` → logged + "❌ Telegram rejected the request."; any other exception → logged + "❌ Something went wrong. Please try again."
- This module may import Telegram; core modules may not.
- Error→message mapping exists **only here**.

### `handlers.py`

- `def authorized(allowed_ids: frozenset[int])` — decorator factory (current wrapper logic, unchanged: private-bot reply when `allowed_ids` non-empty and user not in it).
- `def create_handlers(settings: Settings, runner: JobRunner) -> Handlers` where `Handlers` is a `NamedTuple` with fields `start`, `on_media`, `on_text` (each the bound callable `(Update, ContextTypes.DEFAULT_TYPE) -> Awaitable[None]`):
  - `start` — same welcome text.
  - `on_media` — same attachment pick (`video/audio/voice/video_note/document`), same `fetch` closure that downloads the Telegram file to `tmp`.
  - `on_text` — same `detect_links` handling, same "I need a video/audio file or a link" reply, same per-link `fetch` closure calling `download_audio` via `asyncio.to_thread` with `settings.cookies_file` / `settings.cookies_browser`.
- Every dependency arrives via parameters — no globals, no `context.application` lookups.

### `app.py`

- `build_application(settings: Settings) -> Application` — PTB builder exactly as today (local Bot API base URLs when `bot_api_url` set, `concurrent_updates(True)`), creates `JobRunner(settings, semaphore=Semaphore(settings.max_parallel))`, calls `create_handlers`, registers: `CommandHandler(["start","help"])`, media `MessageHandler`, text `MessageHandler(filters.TEXT & ~filters.COMMAND)`.
- `main()` — `Settings.from_env()`, logging setup, warn if `allowed_ids` empty, `log.info("Bot started")`, `run_polling(allowed_updates=Update.ALL_TYPES)`.

### `__main__.py`

```python
from blackscreen_bot.app import main

main()
```

## Data flow (unchanged)

User message → `authorized` gate → `runner.run(msg, fetch)` (queued status, semaphore, tempdir) → fetch = Telegram file download **or** `download_audio(link)` → `make_black_video` (probe → validate → ffmpeg) → upload-limit check → `reply_video` → status deleted. Status texts, emoji, and error strings are byte-for-byte the same.

## Error handling

- Core modules raise `ProcessingError` only; they never know Telegram exists.
- `jobs.JobRunner.run` is the single boundary that maps exceptions to user-visible status messages (same table as today).
- `yt_dlp.utils.DownloadError` is wrapped into `ProcessingError` inside `download.py`.

## Out of scope

- No new features, config options, or message text changes.
- No test suite (verification below only).
- No packaging metadata (`pyproject.toml`), no console-script entry point.
- No README rewrite.

## Verification

1. `python -m compileall blackscreen_bot` — every file compiles.
2. Import each module in a subprocess with a clean environment (no `BOT_TOKEN` set): all imports succeed with no output and no exception → proves no import-time side effects.
3. Wiring check (script or one-liner): build a `Settings` with a dummy token and `allowed_ids=frozenset({1})`; `build_application(settings)`; assert 3 handlers registered; assert `authorized` blocks user id 2 and passes user id 1.
4. Grep gate: no `import telegram` / `from telegram` inside `config/errors/models/links/download/video`; no module-level `os.environ` access outside `config.from_env`.

## Risks

- **Behavior drift** during code movement: mitigated by keeping moved functions verbatim and limiting edits to signature threading (settings/runner parameters).
- **Import-time env reads** sneaking back: mitigated by verification step 2.
