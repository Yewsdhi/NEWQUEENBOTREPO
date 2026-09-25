#
# ArchonMusic/plugins/play.py
#

from pathlib import Path

from pyrogram import filters, types

from ArchonMusic import ArchonMusic, app, config, db, lang, queue, tg, yt
from ArchonMusic.helpers import buttons, utils
from ArchonMusic.helpers._play import checkUB


def playlist_to_queue(chat_id: int, tracks: list) -> str:
    text = "<blockquote expandable>"
    for track in tracks:
        pos = queue.add(chat_id, track)
        text += f"<b>{pos}.</b> {track.title}\n"
    return text[:1948] + "</blockquote>"


@app.on_message(
    filters.command(["play", "playforce", "vplay", "vplayforce"])
    & filters.group
    & ~app.bl_users
)
@lang.language()
@checkUB
async def play_hndlr(
    _,
    m: types.Message,
    force: bool = False,
    m3u8: bool = False,
    video: bool = False,
    url: str | None = None,
) -> None:
    sent = await m.reply_text(m.lang["play_searching"])
    file = None
    mention = m.from_user.mention
    media = tg.get_media(m.reply_to_message) if m.reply_to_message else None
    tracks = []

    if media:
        sent.lang = m.lang
        file = await tg.download(m.reply_to_message, sent)

    elif m3u8:
        file = await tg.process_m3u8(url, sent.id, video)

    elif url:
        if "playlist" in url:
            await sent.edit_text(m.lang["playlist_fetch"])
            tracks = await yt.playlist(
                config.PLAYLIST_LIMIT,
                mention,
                url,
                video,
            )
            if not tracks:
                return await sent.edit_text(m.lang["playlist_error"])

            file = tracks[0]
            tracks.remove(file)
            file.message_id = sent.id
        else:
            file = await yt.search(url, sent.id, video=video)

        if not file:
            return await sent.edit_text(
                m.lang["play_not_found"].format(config.SUPPORT_CHAT)
            )

    elif len(m.command) >= 2:
        query = " ".join(m.command[1:])
        file = await yt.search(query, sent.id, video=video)
        if not file:
            return await sent.edit_text(
                m.lang["play_not_found"].format(config.SUPPORT_CHAT)
            )

    if not file:
        return await sent.edit_text(m.lang["play_usage"])

    # Normalize older dict-based media objects.
    if isinstance(file, dict):
        file = type("MediaResult", (dict,), {
            "__getattr__": lambda self, name: self[name],
            "__setattr__": lambda self, name, value: self.__setitem__(name, value),
        })(file)

    file.id = getattr(file, "id", None) or getattr(file, "vidid", None)
    file.url = getattr(file, "url", None) or getattr(
        file, "link", f"https://www.youtube.com/watch?v={file.id}"
    )
    file.duration = getattr(file, "duration", None) or getattr(
        file, "duration_min", "0:00"
    )
    file.duration_sec = getattr(file, "duration_sec", None)
    if file.duration_sec is None:
        try:
            parts = [int(x) for x in str(file.duration).split(":")]
            if len(parts) == 3:
                file.duration_sec = parts[0] * 3600 + parts[1] * 60 + parts[2]
            elif len(parts) == 2:
                file.duration_sec = parts[0] * 60 + parts[1]
            else:
                file.duration_sec = parts[0]
        except Exception:
            file.duration_sec = 0

    file.file_path = getattr(file, "file_path", None)

    if file.duration_sec > config.DURATION_LIMIT:
        return await sent.edit_text(
            m.lang["play_duration_limit"].format(config.DURATION_LIMIT // 60)
        )

    if await db.is_logger():
        await utils.play_log(m, sent.link, file.title, file.duration)

    file.user = mention

    if force:
        current = queue.get_current(m.chat.id)
        if current and current.message_id:
            try:
                await app.delete_messages(m.chat.id, current.message_id)
            except Exception:
                pass
        queue.force_add(m.chat.id, file)
    else:
        position = queue.add(m.chat.id, file)

        if position != 0 or await db.get_call(m.chat.id):
            await sent.edit_text(
                m.lang["play_queued"].format(
                    position,
                    file.url,
                    file.title,
                    file.duration,
                    m.from_user.mention,
                ),
                reply_markup=buttons.play_queued(
                    m.chat.id, file.id, m.lang["play_now"]
                ),
            )
            if tracks:
                added = playlist_to_queue(m.chat.id, tracks)
                await app.send_message(
                    chat_id=m.chat.id,
                    text=m.lang["playlist_queued"].format(len(tracks)) + added,
                )
            return

    if not file.file_path:
        await sent.edit_text(m.lang["play_downloading"])

        downloaded = await yt.download(
            file.id,
            video=video,
        )

        if not downloaded:
            return await sent.edit_text(
                "❌ Download failed. Please try another song."
            )

        file.file_path = downloaded

    if not Path(file.file_path).exists():
        return await sent.edit_text(
            "❌ Downloaded file was not found on the server."
        )

    await ArchonMusic.play_media(
        chat_id=m.chat.id,
        message=sent,
        media=file,
    )

    if not tracks:
        return

    added = playlist_to_queue(m.chat.id, tracks)
    await app.send_message(
        chat_id=m.chat.id,
        text=m.lang["playlist_queued"].format(len(tracks)) + added,
            )
                                    
