import time
import asyncio
import logging
from logging.handlers import RotatingFileHandler

logging.basicConfig(
    format="[%(asctime)s - %(levelname)s] - %(name)s: %(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    handlers=[
        RotatingFileHandler(
            "log.txt",
            maxBytes=10485760,
            backupCount=5,
        ),
        logging.StreamHandler(),
    ],
    level=logging.INFO,
)

logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("ntgcalls").setLevel(logging.CRITICAL)
logging.getLogger("pymongo").setLevel(logging.ERROR)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("pytgcalls").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

__version__ = "3.0.2"

from config import Config

config = Config()
config.check()

tasks = []
boot = time.time()


# ==========================================================
# TELEGRAM BOT
# ==========================================================

from ArchonMusic.core.bot import Bot

app = Bot()


# ==========================================================
# DIRECTORIES
# ==========================================================

from ArchonMusic.core.dir import ensure_dirs

ensure_dirs()


# ==========================================================
# USERBOT
# ==========================================================

from ArchonMusic.core.userbot import Userbot

userbot = Userbot()


# ==========================================================
# DATABASE
# ==========================================================

from ArchonMusic.core.mongo import MongoDB

db = MongoDB()


# ==========================================================
# LANGUAGE
# ==========================================================

from ArchonMusic.core.lang import Language

lang = Language()


# ==========================================================
# TELEGRAM HELPERS
# ==========================================================

from ArchonMusic.core.telegram import Telegram

tg = Telegram()


# ==========================================================
# YOUTUBE
#
# IMPORTANT:
# ArchonMusic/core/youtube.py already contains:
#
#     YouTube = YouTubeAPI()
#
# Therefore DO NOT use:
#
#     yt = YouTube()
#
# because YouTube is already an object/instance.
# ==========================================================

from ArchonMusic.core.youtube import YouTube

yt = YouTube


# ==========================================================
# QUEUE / THUMBNAIL
# ==========================================================

from ArchonMusic.helpers import Queue, Thumbnail

queue = Queue()
thumb = Thumbnail()


# ==========================================================
# PYTG CALLS
# ==========================================================

from ArchonMusic.core.calls import TgCall

ArchonMusic = TgCall()


# ==========================================================
# STOP / SHUTDOWN
# ==========================================================

async def stop() -> None:
    logger.info("Stopping...")

    for task in tasks:
        if task.done():
            continue

        task.cancel()

        try:
            await task
        except asyncio.exceptions.CancelledError:
            pass
        except Exception as e:
            logger.error(
                "Error while stopping task: %s",
                e,
            )

    try:
        await app.exit()
    except Exception as e:
        logger.error(
            "Bot shutdown error: %s",
            e,
        )

    try:
        await userbot.exit()
    except Exception as e:
        logger.error(
            "Userbot shutdown error: %s",
            e,
        )

    try:
        await db.close()
    except Exception as e:
        logger.error(
            "Database shutdown error: %s",
            e,
        )

    try:
        await thumb.close()
    except Exception as e:
        logger.error(
            "Thumbnail shutdown error: %s",
            e,
        )

    logger.info("Stopped.\n")
