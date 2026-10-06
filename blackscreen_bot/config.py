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
