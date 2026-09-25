import asyncio
import os
import re
import time
from typing import Union

import aiohttp
import yt_dlp
from py_yt import VideosSearch, Playlist
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message

from config import ARC_API_URL, ARC_API_KEY


def time_to_seconds(time_value):
    stringt = str(time_value)
    try:
        return sum(
            int(x) * 60 ** i
            for i, x in enumerate(reversed(stringt.split(":")))
        )
    except (TypeError, ValueError):
        return 0


async def _arc_request_download(video_id: str, is_video: bool) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{ARC_API_URL.rstrip('/')}/youtube/v2/download",
            params={
                "query": video_id,
                "isVideo": str(is_video).lower(),
                "api_key": ARC_API_KEY,
            },
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                return {}
            try:
                return await resp.json(content_type=None)
            except Exception:
                return {}


async def _arc_poll_job(
    job_id: str, retries: int = 15, interval: int = 3
) -> str | None:
    async with aiohttp.ClientSession() as session:
        for _ in range(retries):
            try:
                async with session.get(
                    f"{ARC_API_URL.rstrip('/')}/youtube/jobStatus",
                    params={"job_id": job_id, "api_key": ARC_API_KEY},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        job = data.get("job", {})
                        if job.get("status") == "done":
                            return job.get("result", {}).get("cdn")
                        if job.get("status") == "error":
                            return None
            except Exception:
                pass
            await asyncio.sleep(interval)
    return None


async def _arc_get_cdn(video_id: str, is_video: bool) -> str | None:
    data = await _arc_request_download(video_id, is_video)
    if not data:
        return None

    job_id = data.get("job_id")
    if not job_id:
        return (data.get("result") or {}).get("cdn")

    return await _arc_poll_job(job_id)


async def _save_from_cdn(cdn: str, file_path: str) -> bool:
    match = re.match(
        r"https?://(?:t\.me|telegram\.dog)/([^/]+)/(\d+)", cdn
    )

    if match:
        # Lazy import avoids ArchonMusic circular import during startup.
        from ArchonMusic import app

        username, message_id = match.group(1), int(match.group(2))
        msg = await app.get_messages(username, message_id)

        if not msg or not (msg.audio or msg.video or msg.document):
            return False

        downloaded = await app.download_media(msg, file_name=file_path)
        return bool(downloaded)

    async with aiohttp.ClientSession() as session:
        async with session.get(
            cdn, timeout=aiohttp.ClientTimeout(total=600)
        ) as resp:
            if resp.status != 200:
                return False

            with open(file_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(131072):
                    f.write(chunk)

    return True


def _extract_video_id(link: str) -> str:
    if not link:
        return ""

    link = str(link).strip()

    if "youtu.be/" in link:
        return (
            link.split("youtu.be/", 1)[1]
            .split("?", 1)[0]
            .split("&", 1)[0]
        )

    if "youtube.com/shorts/" in link:
        return (
            link.split("youtube.com/shorts/", 1)[1]
            .split("?", 1)[0]
            .split("&", 1)[0]
        )

    if "v=" in link:
        return link.split("v=", 1)[1].split("&", 1)[0]

    return link


async def download_song(link: str) -> str | None:
    video_id = _extract_video_id(link)

    if not video_id or len(video_id) < 3:
        return None

    os.makedirs("downloads", exist_ok=True)
    file_path = os.path.join("downloads", f"{video_id}.mp3")

    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    try:
        cdn = await _arc_get_cdn(video_id, is_video=False)

        if not cdn:
            return None

        if not await _save_from_cdn(cdn, file_path):
            return None

        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return file_path

    except Exception:
        pass

    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass

    return None


async def download_video(link: str) -> str | None:
    video_id = _extract_video_id(link)

    if not video_id or len(video_id) < 3:
        return None

    os.makedirs("downloads", exist_ok=True)
    file_path = os.path.join("downloads", f"{video_id}.mp4")

    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    try:
        cdn = await _arc_get_cdn(video_id, is_video=True)

        if not cdn:
            return None

        if not await _save_from_cdn(cdn, file_path):
            return None

        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return file_path

    except Exception:
        pass

    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass

    return None


async def _yt_direct_audio_url(link: str) -> str | None:
    # Resolve a direct YouTube audio URL for PyTgCalls playback.

    def _resolve():
        opts = {
            "format": "bestaudio[acodec!=opus]/bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "socket_timeout": 8,
            "retries": 1,
            "fragment_retries": 1,
            "extractor_retries": 1,
            "skip_unavailable_fragments": True,
            "extractor_args": {
                "youtube": {
                    "player_client": [
                        "android_vr",
                        "web_safari",
                        "mweb",
                    ],
                }
            },
        }

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(link, download=False)

            if info and info.get("url"):
                return info["url"]

            formats = (info or {}).get("formats") or []

            for fmt in reversed(formats):
                url = fmt.get("url")
                acodec = fmt.get("acodec")

                if url and acodec and acodec != "none":
                    return url

        return None

    try:
        return await asyncio.to_thread(_resolve)
    except Exception:
        return None


_DIRECT_URL_CACHE = {}
_DIRECT_URL_CACHE_TTL = 90


class YouTubeSearchResult(dict):
    # Dict-compatible result with attribute access for play.py.

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(
                f"{self.__class__.__name__} object has no attribute '{name}'"
            )


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(
            r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
        )

    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if not link:
            return False

        if videoid:
            link = self.base + link

        return bool(re.search(self.regex, str(link)))

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]

        if getattr(message_1, "reply_to_message", None):
            messages.append(message_1.reply_to_message)

        for message in messages:
            entities = getattr(message, "entities", None) or []

            for entity in entities:
                if entity.type == MessageEntityType.URL:
                    text_value = message.text or message.caption or ""
                    return text_value[
                        entity.offset: entity.offset + entity.length
                    ]

            caption_entities = (
                getattr(message, "caption_entities", None) or []
            )

            for entity in caption_entities:
                if entity.type == MessageEntityType.TEXT_LINK:
                    return entity.url

        return None

    async def search(self, query: str, user_id=None, video=False):
        # Return a play.py-compatible object.
        try:
            if not query:
                return None

            query = str(query).strip()

            if "youtube.com" in query or "youtu.be" in query:
                if "&" in query:
                    query = query.split("&", 1)[0]

            results = VideosSearch(query, limit=1)
            data = await results.next()
            items = (data or {}).get("result") or []

            if not items:
                return None

            item = items[0]

            vidid = item.get("id")
            if not vidid:
                return None

            link = item.get("link")
            if not link:
                link = f"https://www.youtube.com/watch?v={vidid}"

            title = item.get("title") or "Unknown Title"
            duration_min = item.get("duration") or "0:00"

            duration_sec = time_to_seconds(duration_min)

            thumbnails = item.get("thumbnails") or []
            thumbnail = ""

            if thumbnails:
                thumbnail = (
                    thumbnails[0].get("url") or ""
                ).split("?")[0]

            channel = item.get("channel") or {}

            if isinstance(channel, dict):
                artist = channel.get("name") or "Unknown Artist"
            else:
                artist = "Unknown Artist"

            return YouTubeSearchResult(
                title=title,
                link=link,
                url=link,
                vidid=vidid,
                videoid=vidid,

                # Both names are kept because different ArchonMusic
                # modules use different duration keys.
                duration=duration_min,
                duration_min=duration_min,
                duration_sec=duration_sec,

                thumbnail=thumbnail,
                thumb=thumbnail,

                artist=artist,
                channel=artist,

                video=bool(video),
                user_id=user_id,
            )

        except Exception as e:
            print(f"[YouTube Search Error] {e}")
            return None

    async def details(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + link

        if "&" in link:
            link = link.split("&", 1)[0]

        try:
            results = VideosSearch(link, limit=1)
            data = await results.next()
            items = (data or {}).get("result") or []

            if not items:
                return None, "0:00", 0, "", ""

            result = items[0]

            title = result.get("title") or "Unknown Title"
            duration_min = result.get("duration") or "0:00"

            thumbs = result.get("thumbnails") or []
            thumbnail = ""

            if thumbs:
                thumbnail = (
                    thumbs[0].get("url") or ""
                ).split("?")[0]

            vidid = result.get("id") or ""
            duration_sec = time_to_seconds(duration_min)

            return (
                title,
                duration_min,
                duration_sec,
                thumbnail,
                vidid,
            )

        except Exception:
            return None, "0:00", 0, "", ""

    async def title(self, link: str, videoid: Union[bool, str] = None):
        details = await self.details(link, videoid)
        return details[0] if details else None

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        details = await self.details(link, videoid)
        return details[1] if details else "0:00"

    async def thumbnail(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        details = await self.details(link, videoid)
        return details[3] if details else ""

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link

        try:
            downloaded_file = await download_video(link)

            if downloaded_file:
                return 1, downloaded_file

            return 0, "Video download failed"

        except Exception as e:
            return 0, f"Video download error: {e}"

    async def playlist(
        self,
        link,
        limit,
        user_id,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.listbase + link

        if "&" in link:
            link = link.split("&", 1)[0]

        try:
            plist = await Playlist.get(link)
            videos = plist.get("videos") or []
        except Exception:
            return []

        ids = []

        for data in videos[:limit]:
            if not data:
                continue

            vid = data.get("id")

            if vid:
                ids.append(vid)

        return ids

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link

        if "&" in link:
            link = link.split("&", 1)[0]

        try:
            results = VideosSearch(link, limit=1)
            data = await results.next()
            items = (data or {}).get("result") or []

            if not items:
                return {}, None

            result = items[0]

            title = result.get("title") or "Unknown Title"
            duration_min = result.get("duration") or "0:00"
            vidid = result.get("id") or ""

            yturl = result.get("link")
            if not yturl:
                yturl = f"https://www.youtube.com/watch?v={vidid}"

            thumbs = result.get("thumbnails") or []
            thumbnail = ""

            if thumbs:
                thumbnail = (
                    thumbs[0].get("url") or ""
                ).split("?")[0]

            track_details = {
                "title": title,
                "link": yturl,
                "vidid": vidid,
                "duration_min": duration_min,
                "duration": duration_min,
                "thumb": thumbnail,
                "thumbnail": thumbnail,
            }

            return track_details, vidid

        except Exception:
            return {}, None

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link

        if "&" in link:
            link = link.split("&", 1)[0]

        try:
            ytdl_opts = {
                "quiet": True,
                "no_warnings": True,
            }

            with yt_dlp.YoutubeDL(ytdl_opts) as ydl:
                result = ydl.extract_info(link, download=False)

            formats_available = []

            for fmt in (result or {}).get("formats") or []:
                try:
                    if "dash" in str(fmt.get("format", "")).lower():
                        continue

                    formats_available.append(
                        {
                            "format": fmt.get("format"),
                            "filesize": fmt.get("filesize"),
                            "format_id": fmt.get("format_id"),
                            "ext": fmt.get("ext"),
                            "format_note": fmt.get("format_note"),
                            "yturl": link,
                        }
                    )

                except Exception:
                    continue

            return formats_available, link

        except Exception:
            return [], link

    async def slider(
        self,
        link: str,
        query_type: int,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + link

        if "&" in link:
            link = link.split("&", 1)[0]

        try:
            results = VideosSearch(link, limit=10)
            data = await results.next()
            items = (data or {}).get("result") or []

            if not items or query_type >= len(items):
                return None, "0:00", "", ""

            item = items[query_type]

            title = item.get("title") or "Unknown Title"
            duration_min = item.get("duration") or "0:00"
            vidid = item.get("id") or ""

            thumbs = item.get("thumbnails") or []
            thumbnail = ""

            if thumbs:
                thumbnail = (
                    thumbs[0].get("url") or ""
                ).split("?")[0]

            return (
                title,
                duration_min,
                thumbnail,
                vidid,
            )

        except Exception:
            return None, "0:00", "", ""

    async def stream_url(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + link

        if "&" in link:
            link = link.split("&", 1)[0]

        key = link
        cached = _DIRECT_URL_CACHE.get(key)
        now = time.monotonic()

        if cached and cached[1] > now:
            return cached[0]

        if cached:
            _DIRECT_URL_CACHE.pop(key, None)

        url = await _yt_direct_audio_url(link)

        if url:
            _DIRECT_URL_CACHE[key] = (
                url,
                now + _DIRECT_URL_CACHE_TTL,
            )

        return url

    async def download(
        self,
        link: str,
        mystic,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + link

        try:
            if video:
                downloaded_file = await download_video(link)
            else:
                downloaded_file = await download_song(link)

            if downloaded_file:
                return downloaded_file, True

            return None, False

        except Exception:
            return None, False


YouTube = YouTubeAPI()
     
