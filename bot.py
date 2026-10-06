#!/usr/bin/env python3
"""Telegram bot: send a video/audio file or a Facebook/Instagram/X link,
get back a black-screen video with the original audio."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from telegram import Message, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import processor
from processor import ProcessingError

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("blackscreen-bot")

# ----------------------------- configuration ------------------------------- #
BOT_TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_IDS = {int(x) for x in os.getenv("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x}
BOT_API_URL = os.getenv("BOT_API_URL")  # e.g. http://localhost:8081 (local Bot API server)
COOKIES_FILE = os.getenv("COOKIES_FILE") or None
COOKIES_BROWSER = os.getenv("COOKIES_FROM_BROWSER") or None
MAX_DURATION = float(os.getenv("MAX_DURATION_MIN", "90")) * 60
MAX_PARALLEL = int(os.getenv("MAX_PARALLEL_JOBS", "2"))
UPLOAD_LIMIT = (2000 if BOT_API_URL else 50) * 1024 * 1024  # Telegram upload limits

try:
    w, h = os.getenv("BLACK_SIZE", "1280x720").lower().split("x")
    DEFAULT_SIZE = (int(w), int(h))
except ValueError:
    DEFAULT_SIZE = processor.DEFAULT_SIZE

JOBS = asyncio.Semaphore(MAX_PARALLEL)


# ------------------------------- helpers ----------------------------------- #
def authorized(handler):
    @wraps(handler)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if ALLOWED_IDS and (not user or user.id not in ALLOWED_IDS):
            if update.effective_message:
                await update.effective_message.reply_text("Sorry, this bot is private.")
            return
        return await handler(update, ctx)

    return wrapper


async def convert_and_send(msg: Message, src: Path, tmp: Path, status: Message) -> None:
    out = tmp / f"black_{src.stem}.mp4"

    await status.edit_text("🎬 Converting...")
    info = await asyncio.to_thread(
        processor.make_black_video, src, out, DEFAULT_SIZE, MAX_DURATION
    )

    if out.stat().st_size > UPLOAD_LIMIT:
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


async def run_job(msg: Message, fetch) -> None:
    """fetch(tmp, status) -> Path to the source media."""
    status = await msg.reply_text("⏳ Queued...", quote=True)
    async with JOBS:
        with tempfile.TemporaryDirectory(prefix="bsbot_") as t:
            tmp = Path(t)
            try:
                src = await fetch(tmp, status)
                await convert_and_send(msg, src, tmp, status)
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


# ------------------------------- handlers ---------------------------------- #
@authorized
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me:\n"
        "• a video or audio file\n"
        "• a Facebook / Instagram / X link\n\n"
        "and I'll send back a black-screen video with the same audio."
    )


@authorized
async def on_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    att = msg.video or msg.audio or msg.voice or msg.video_note or msg.document

    async def fetch(tmp: Path, status: Message) -> Path:
        await status.edit_text("⬇️ Downloading file...")
        tg_file = await att.get_file()
        suffix = Path(tg_file.file_path or "").suffix or ".bin"
        dest = tmp / f"{att.file_unique_id}{suffix}"
        await tg_file.download_to_drive(dest)
        return Path(dest)

    await run_job(msg, fetch)


@authorized
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    links = processor.detect_links(msg.text)
    if not links:
        await msg.reply_text("I need a video/audio file or a Facebook / Instagram / X link.")
        return

    for link in links:
        async def fetch(tmp: Path, status: Message, link=link) -> Path:
            await status.edit_text(f"⬇️ Downloading from {link.platform}...")
            return await asyncio.to_thread(
                processor.download_audio, link.url, tmp, COOKIES_FILE, COOKIES_BROWSER
            )

        await run_job(msg, fetch)


def main():
    builder = Application.builder().token(BOT_TOKEN)
    if BOT_API_URL:
        builder = (
            builder.base_url(f"{BOT_API_URL}/bot")
            .base_file_url(f"{BOT_API_URL}/file/bot")
            .local_mode(True)
        )
    app = builder.concurrent_updates(True).build()

    media = (
        filters.VIDEO | filters.AUDIO | filters.VOICE | filters.VIDEO_NOTE
        | filters.Document.VIDEO | filters.Document.AUDIO
    )
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(MessageHandler(media, on_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    if not ALLOWED_IDS:
        log.warning("ALLOWED_USER_IDS is empty: anyone can use this bot!")
    log.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()