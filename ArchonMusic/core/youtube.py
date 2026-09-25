import asyncio
import os
import re
import time
from typing import Union

import aiohttp
import yt_dlp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from py_yt import Playlist, VideosSearch

from config import ARC_API_URL, ARC_API_KEY


def time_to_seconds(value):
    try:
        parts = [int(x) for x in str(value).split(":")]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return int(parts[0])
    except Exception:
        return 0


def _video_id(link: str) -> str:
    link = str(link or "").strip()
    if "youtu.be/" in link:
        return link.split("youtu.be/", 1)[1].split("?", 1)[0].split("&", 1)[0]
    if "v=" in link:
        return link.split("v=", 1)[1].split("&", 1)[0]
    return link


async def _arc_request_download(video_id: str, is_video: bool) -> dict:
    try:
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
                return await resp.json(content_type=None)
    except Exception as e:
        print(f"[ARC request error] {e}")
        return {}


async def _arc_poll_job(job_id: str, retries: int = 20, interval: int = 3):
    async with aiohttp.ClientSession() as session:
        for _ in range(retries):
            try:
                async with session.get(
                    f"{ARC_API_URL.rstrip('/')}/youtube/jobStatus",
                    params={"job_id": job_id, "api_key": ARC_API_KEY},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        job = data.get("job") or {}
                        status = job.get("status")
                        if status == "done":
                            return (job.get("result") or {}).get("cdn")
                        if status == "error":
                            return None
            except Exception as e:
                print(f"[ARC poll error] {e}")
            await asyncio.sleep(interval)
    return None


async def _arc_get_cdn(video_id: str, is_video: bool):
    data = await _arc_request_download(video_id, is_video)
    if not data:
        return None

    job_id = data.get("job_id")
    if job_id:
        return await _arc_poll_job(job_id)

    return (data.get("result") or {}).get("cdn")


async def _save_from_cdn(cdn: str, file_path: str) -> bool:
    # Imported locally to avoid the ArchonMusic <-> youtube circular import.
    if re.match(r"https?://(?:t\.me|telegram\.dog)/[^/]+/\d+", cdn):
        from ArchonMusic import app

        match = re.match(
            r"https?://(?:t\.me|telegram\.dog)/([^/]+)/(\d+)",
            cdn,
        )
        if not match:
            return False

        username, message_id = match.group(1), int(match.group(2))
        try:
            msg = await app.get_messages(username, message_id)
            if not msg or not (msg.audio or msg.video or msg.document):
                return False
            downloaded = await app.download_media(msg, file_name=file_path)
            return bool(downloaded)
        except Exception as e:
            print(f"[Telegram CDN error] {e}")
            return False

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                cdn,
                timeout=aiohttp.ClientTimeout(total=600),
            ) as resp:
                if resp.status != 200:
                    return False
                with open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(131072):
                        f.write(chunk)
        return os.path.exists(file_path) and os.path.getsize(file_path) > 0
    except Exception as e:
        print(f"[CDN download error] {e}")
        return False


async def download_song(link: str):
    video_id = _video_id(link)
    if len(video_id) < 3:
        return None

    os.makedirs("downloads", exist_ok=True)
    file_path = f"downloads/{video_id}.mp3"

    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    try:
        cdn = await _arc_get_cdn(video_id, False)
        if not cdn or not await _save_from_cdn(cdn, file_path):
            return None
        return file_path if os.path.exists(file_path) else None
    except Exception as e:
        print(f"[Audio download error] {e}")
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
        return None


async def download_video(link: str):
    video_id = _video_id(link)
    if len(video_id) < 3:
        return None

    os.makedirs("downloads", exist_ok=True)
    file_path = f"downloads/{video_id}.mp4"

    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    try:
        cdn = await _arc_get_cdn(video_id, True)
        if not cdn or not await _save_from_cdn(cdn, file_path):
            return None
        return file_path if os.path.exists(file_path) else None
    except Exception as e:
        print(f"[Video download error] {e}")
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
        return None


_DIRECT_URL_CACHE = {}
_DIRECT_URL_CACHE_TTL = 90


async def _yt_direct_audio_url(link: str):
    def resolve():
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
                    "player_client": ["android_vr", "web_safari", "mweb"],
                }
            },
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(link, download=False)
            if info and info.get("url"):
                return info["url"]
            for fmt in reversed((info or {}).get("formats") or []):
                url = fmt.get("url")
                acodec = fmt.get("acodec")
                if url and acodec and acodec != "none":
                    return url
        return None

    try:
        return await asyncio.to_thread(resolve)
    except Exception as e:
        print(f"[yt-dlp stream error] {e}")
        return None


class YouTubeSearchResult(dict):
    """Dict with attribute access for the existing ArchonMusic queue/play code."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(
                f"{type(self).__name__} object has no attribute {name!r}"
            ) from exc

    def __setattr__(self, name, value):
        self[name] = value


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    @staticmethod
    def _clean_link(link: str):
        link = str(link or "").strip()
        if "&" in link:
            link = link.split("&", 1)[0]
        return link

    @staticmethod
    def _make_result(item, user_id=None, video=False):
        vidid = item.get("id")
        if not vidid:
            return None

        link = item.get("link") or f"https://www.youtube.com/watch?v={vidid}"
        title = item.get("title") or "Unknown Title"
        duration = item.get("duration") or "0:00"

        thumbs = item.get("thumbnails") or []
        thumbnail = ""
        if thumbs:
            thumbnail = (thumbs[0].get("url") or "").split("?")[0]

        channel = item.get("channel") or {}
        artist = (
            channel.get("name")
            if isinstance(channel, dict)
            else str(channel or "")
        ) or "Unknown Artist"

        return YouTubeSearchResult(
            id=vidid,
            title=title,
            link=link,
            url=link,
            vidid=vidid,
            videoid=vidid,
            duration=duration,
            duration_min=duration,
            duration_sec=time_to_seconds(duration),
            thumbnail=thumbnail,
            thumb=thumbnail,
            artist=artist,
            channel=artist,
            video=bool(video),
            user_id=user_id,
            file_path=None,
        )

    async def search(self, query: str, user_id=None, video=False):
        try:
            if not query:
                return None

            query = str(query).strip()
            results = VideosSearch(query, limit=1)
            data = await results.next()
            items = (data or {}).get("result") or []

            if not items:
                return None

            return self._make_result(items[0], user_id, video)
        except Exception as e:
            print(f"[YouTube Search Error] {e}")
            return None

    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + str(link)
        return bool(re.search(self.regex, str(link or "")))

    async def url(self, message_1: Message):
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)

        for message in messages:
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption or ""
                        return text[entity.offset:entity.offset + entity.length]
            if message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        return None

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + str(link)
        link = self._clean_link(link)
        results = VideosSearch(link, limit=1)
        data = await results.next()
        items = (data or {}).get("result") or []
        if not items:
            return None
        r = items[0]
        duration = r.get("duration") or "0:00"
        thumbs = r.get("thumbnails") or []
        thumbnail = (thumbs[0].get("url") or "").split("?")[0] if thumbs else ""
        return (
            r.get("title") or "Unknown Title",
            duration,
            time_to_seconds(duration),
            thumbnail,
            r.get("id"),
        )

    async def title(self, link: str, videoid: Union[bool, str] = None):
        details = await self.details(link, videoid)
        return details[0] if details else None

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        details = await self.details(link, videoid)
        return details[1] if details else None

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        details = await self.details(link, videoid)
        return details[3] if details else None

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + str(link)
        try:
            downloaded = await download_video(link)
            return (1, downloaded) if downloaded else (0, "Video download failed")
        except Exception as e:
            return 0, f"Video download error: {e}"

    async def playlist(
        self,
        limit: int,
        user_id,
        link: str,
        video: Union[bool, str] = False,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.listbase + str(link)
        link = self._clean_link(link)

        try:
            plist = await Playlist.get(link)
        except Exception as e:
            print(f"[YouTube Playlist Error] {e}")
            return []

        tracks = []
        for item in (plist.get("videos") or [])[:limit]:
            result = self._make_result(item, user_id, video)
            if result:
                tracks.append(result)
        return tracks

    async def track(self, link: str, videoid: Union[bool, str] = None):
        result = await self.search(
            self.base + str(link) if videoid else link,
            None,
            False,
        )
        if not result:
            return None, None
        return {
            "title": result.title,
            "link": result.link,
            "vidid": result.id,
            "duration_min": result.duration,
            "thumb": result.thumbnail,
        }, result.id

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + str(link)
        link = self._clean_link(link)
        ytdl_opts = {"quiet": True}
        with yt_dlp.YoutubeDL(ytdl_opts) as ydl:
            info = ydl.extract_info(link, download=False)
            formats_available = []
            for fmt in (info or {}).get("formats") or []:
                try:
                    if "dash" not in str(fmt.get("format", "")).lower():
                        formats_available.append({
                            "format": fmt.get("format"),
                            "filesize": fmt.get("filesize"),
                            "format_id": fmt.get("format_id"),
                            "ext": fmt.get("ext"),
                            "format_note": fmt.get("format_note"),
                            "yturl": link,
                        })
                except Exception:
                    continue
        return formats_available, link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + str(link)
        link = self._clean_link(link)
        result = (await VideosSearch(link, limit=10).next()).get("result") or []
        if query_type >= len(result):
            return None
        item = result[query_type]
        duration = item.get("duration") or "0:00"
        thumbs = item.get("thumbnails") or []
        thumb = (thumbs[0].get("url") or "").split("?")[0] if thumbs else ""
        return item.get("title"), duration, thumb, item.get("id")

    async def stream_url(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + str(link)
        link = self._clean_link(link)

        now = time.monotonic()
        cached = _DIRECT_URL_CACHE.get(link)
        if cached and cached[1] > now:
            return cached[0]
        if cached:
            _DIRECT_URL_CACHE.pop(link, None)

        url = await _yt_direct_audio_url(link)
        if url:
            _DIRECT_URL_CACHE[link] = (url, now + _DIRECT_URL_CACHE_TTL)
        return url

    async def download(
        self,
        link: str,
        mystic=None,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + str(link)

        try:
            downloaded = await (
                download_video(link) if video else download_song(link)
            )
            # IMPORTANT: play.py expects a string path, not (path, True).
            return downloaded
        except Exception as e:
            print(f"[YouTube Download Error] {e}")
            return None


YouTube = YouTubeAPI()
        
