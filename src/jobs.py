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

from src.config import Settings
from src.errors import ProcessingError
from src.video import make_black_video

log = logging.getLogger("blackscreen-bot")

Fetch = Callable[[Path, Message], Awaitable[Path]]


@dataclass
class JobRunner:
    settings: Settings
    semaphore: asyncio.Semaphore

    async def run(self, msg: Message, fetch: Fetch) -> None:
        status = await msg.reply_text("⏳ Queued...", do_quote=True)
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
