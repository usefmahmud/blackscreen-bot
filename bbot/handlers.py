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

from bbot import download, links
from bbot.config import Settings
from bbot.jobs import JobRunner

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
