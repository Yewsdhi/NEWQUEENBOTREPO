#
# Copyright (C) 2025-present by TheAloneTeam@Github
#

import asyncio
import os
import re

import aiohttp
from PIL import (
    Image,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
)

from ArchonMusic import config
from ArchonMusic.helpers import Track


class Thumbnail:
    def __init__(self):
        self.rect = (914, 514)
        self.fill = (255, 255, 255)

        try:
            self.font1 = ImageFont.truetype(
                "ArchonMusic/helpers/Raleway-Bold.ttf",
                30,
            )
            self.font2 = ImageFont.truetype(
                "ArchonMusic/helpers/Inter-Light.ttf",
                30,
            )
        except Exception:
            self.font1 = ImageFont.load_default()
            self.font2 = ImageFont.load_default()

        self.session: aiohttp.ClientSession | None = None

    async def start(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

        self.session = None

    async def save_thumb(self, output_path: str, url: str) -> str:
        await self.start()

        async with self.session.get(url) as resp:
            resp.raise_for_status()

            data = await resp.read()

        with open(output_path, "wb") as f:
            f.write(data)

        return output_path

    @staticmethod
    def _is_youtube_url(text: str) -> bool:
        if not text:
            return False

        text = str(text).strip().lower()

        return bool(
            re.match(
                r"^(https?://)?(www\.)?"
                r"(youtube\.com|youtu\.be)/",
                text,
            )
        )

    @staticmethod
    def _clean_title(title: str) -> str:
        """
        Never display a YouTube URL as the song title.
        """
        if not title:
            return "Unknown"

        title = str(title).strip()

        if not title:
            return "Unknown"

        if Thumbnail._is_youtube_url(title):
            return "Unknown"

        # Remove excessive whitespace.
        title = re.sub(r"\s+", " ", title)

        return title[:70]

    def _draw_image(
        self,
        temp,
        output,
        song: Track,
        size=(1280, 720),
    ):
        source = Image.open(temp).convert("RGB")

        # Background
        background = ImageOps.fit(
            source,
            size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

        # Blur
        background = background.filter(
            ImageFilter.GaussianBlur(
                radius=max(8, int(min(size) * 0.025))
            )
        )

        # Darken background
        background = ImageEnhance.Brightness(
            background
        ).enhance(0.40)

        # Main thumbnail
        foreground = ImageOps.contain(
            source,
            self.rect,
            method=Image.Resampling.LANCZOS,
        )

        x = (size[0] - foreground.width) // 2
        y = (size[1] - foreground.height) // 2

        # Rounded corners
        mask = Image.new(
            "L",
            foreground.size,
            0,
        )

        ImageDraw.Draw(mask).rounded_rectangle(
            (
                0,
                0,
                foreground.width,
                foreground.height,
            ),
            radius=15,
            fill=255,
        )

        foreground = foreground.convert("RGBA")
        foreground.putalpha(mask)

        background = background.convert("RGBA")

        background.paste(
            foreground,
            (x, y),
            foreground,
        )

        draw = ImageDraw.Draw(background)

        # Channel + views
        channel = str(
            getattr(song, "channel_name", None)
            or "Unknown"
        ).strip()

        views = getattr(song, "view_count", 0) or 0

        draw.text(
            xy=(50, 560),
            text=f"{channel[:25]} | {views}",
            font=self.font2,
            fill=self.fill,
        )

        # -------------------------------------------------
        # SONG TITLE
        # -------------------------------------------------
        raw_title = getattr(song, "title", None)

        title = self._clean_title(raw_title)

        draw.text(
            (50, 600),
            title,
            font=self.font1,
            fill=self.fill,
        )

        # Progress
        draw.text(
            (40, 650),
            "0:01",
            font=self.font1,
            fill=self.fill,
        )

        draw.line(
            [(140, 670), (1160, 670)],
            fill=self.fill,
            width=5,
            joint="curve",
        )

        # Duration
        duration = getattr(
            song,
            "duration",
            None,
        ) or "00:00"

        draw.text(
            (1185, 650),
            str(duration),
            font=self.font1,
            fill=self.fill,
        )

        background.convert("RGB").save(
            output,
            quality=95,
        )

        return output

    async def generate(
        self,
        song: Track,
        size=(1280, 720),
        user_avatar=None,
    ) -> str:
        """
        Generate song thumbnail.

        user_avatar is kept for compatibility.
        """

        song_id = str(
            getattr(song, "id", "unknown")
        )

        temp = f"cache/temp_{song_id}.jpg"
        output = f"cache/{song_id}.png"

        try:
            os.makedirs(
                "cache",
                exist_ok=True,
            )

            # Use cached thumbnail if available.
            if os.path.exists(output):
                return output

            thumbnail = getattr(
                song,
                "thumbnail",
                None,
            )

            if not thumbnail:
                return config.DEFAULT_THUMB

            await self.save_thumb(
                temp,
                thumbnail,
            )

            await asyncio.to_thread(
                self._draw_image,
                temp,
                output,
                song,
                size,
            )

            return output

        except Exception:
            return config.DEFAULT_THUMB

        finally:
            try:
                if os.path.exists(temp):
                    os.remove(temp)
            except Exception:
                pass
