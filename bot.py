import os
import re
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from dotenv import load_dotenv
import yt_dlp
from shazamio import Shazam

# Инициализация FFmpeg
try:
    from static_ffmpeg import add_paths
    add_paths()
except ImportError:
    pass

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not API_ID or not API_HASH:
    raise RuntimeError("❌ API_ID или API_HASH не заданы в .env файле!")

DOWNLOAD_DIR = "downloads"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ─── Клиент ────────────────────────────────────────────────────────────────────
app = Client(
    "my_user_session",
    api_id=int(API_ID),
    api_hash=API_HASH,
    workdir=".",
    sleep_threshold=60,
    # Получаем обновления из всех чатов, включая большие супергруппы
    max_concurrent_transmissions=5,
)

shazam = Shazam()

# ─── Расшифровка ошибок yt-dlp ─────────────────────────────────────────────────
def parse_ytdlp_error(e: Exception) -> str:
    msg = str(e).lower()

    if "private video" in msg:
        return "🔒 Видео приватное — доступ закрыт"
    if "members-only" in msg:
        return "👥 Видео только для участников канала"
    if "age" in msg and ("restrict" in msg or "confirm" in msg):
        return "🔞 Видео с возрастным ограничением — не могу скачать без авторизации"
    if "copyright" in msg or "removed" in msg:
        return "©️ Видео удалено по авторским правам"
    if "not available" in msg or "unavailable" in msg:
        return "🌍 Видео недоступно (возможно, заблокировано в вашем регионе)"
    if "404" in msg or "not found" in msg:
        return "🔍 Видео не найдено (404)"
    if "403" in msg or "forbidden" in msg:
        return "🚫 Доступ запрещён платформой (403)"
    if "429" in msg or "too many" in msg:
        return "⏳ Слишком много запросов — попробуй через минуту"
    if "no video formats" in msg or "no formats" in msg:
        return "📭 Не найдено подходящих форматов для скачивания"
    if "unable to extract" in msg or "unsupported url" in msg:
        return "🔗 Неподдерживаемая ссылка или сайт"
    if "sign in" in msg or "login" in msg:
        return "🔑 Для скачивания нужна авторизация на платформе"
    if "live" in msg:
        return "📡 Прямые трансляции скачивать нельзя"
    if "no matching formats" in msg:
        return "📦 Подходящий формат не найден (возможно, только аудио)"
    if "ffmpeg" in msg:
        return "🔧 Ошибка FFmpeg — проверь его установку"
    if "network" in msg or "connection" in msg or "timeout" in msg:
        return "🌐 Ошибка сети — нет соединения или таймаут"
    if "no results" in msg or "no video" in msg:
        return "🔍 По запросу ничего не найдено"

    # Вернуть первую вменяемую строку из оригинала
    first_line = str(e).split("\n")[0][:80]
    return f"⚠️ {first_line}"


# ─── Скачивание через yt-dlp ───────────────────────────────────────────────────
def download_audio_soundcloud(query: str):
    """Скачивание музыки с SoundCloud (настоящие треки, не YouTube)"""
    file_template = os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s")
    ydl_opts = {
        'outtmpl': file_template,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'format': 'bestaudio/best',
        'default_search': 'scsearch',   # ← SoundCloud Search
        'max_downloads': 1,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=True)
        if 'entries' in info and info['entries']:
            info = info['entries'][0]

        filename = ydl.prepare_filename(info)
        filename = os.path.splitext(filename)[0] + ".mp3"

        return (
            filename,
            info.get('title', 'Неизвестно'),
            info.get('duration', 0),
            info.get('uploader', 'Неизвестно'),
        )


def download_video(url: str):
    """Скачивание видео по прямой ссылке"""
    file_template = os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s")
    ydl_opts = {
        'outtmpl': file_template,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'max_filesize': 1.5 * 1024 * 1024 * 1024,  # 1.5 ГБ
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if 'entries' in info and info['entries']:
            info = info['entries'][0]

        filename = ydl.prepare_filename(info)
        if not os.path.exists(filename):
            base = os.path.splitext(filename)[0]
            if os.path.exists(base + ".mp4"):
                filename = base + ".mp4"

        return (
            filename,
            info.get('title', 'Неизвестно'),
            info.get('duration', 0),
        )


def search_and_download_video(query: str):
    """Поиск видео на YouTube по запросу и скачивание"""
    file_template = os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s")
    ydl_opts = {
        'outtmpl': file_template,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'default_search': 'ytsearch',
        'max_downloads': 1,
        'max_filesize': 1.5 * 1024 * 1024 * 1024,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=True)
        if 'entries' in info and info['entries']:
            info = info['entries'][0]

        filename = ydl.prepare_filename(info)
        if not os.path.exists(filename):
            base = os.path.splitext(filename)[0]
            if os.path.exists(base + ".mp4"):
                filename = base + ".mp4"

        return (
            filename,
            info.get('title', 'Неизвестно'),
            info.get('duration', 0),
            f"https://youtu.be/{info.get('id', '')}",
        )


# ─── Хелпер: достать команду и аргумент ───────────────────────────────────────
def extract_query(text: str, commands: list[str]) -> str | None:
    """Возвращает текст после команды, или None если команды нет."""
    low = text.lower()
    for cmd in commands:
        if low.startswith(cmd):
            return text[len(cmd):].strip()
    return None


# ─── Единый обработчик ────────────────────────────────────────────────────────
# ВАЖНО: убрали фильтр по типу чата — в больших супергруппах filters.group
# не всегда срабатывает. Теперь слушаем всё, кроме ботов.
@app.on_message(filters.text & ~filters.bot)
async def handle_everything(client: Client, message: Message):
    if not message.text:
        return

    raw = message.text.strip()
    low = raw.lower()
    is_me = message.from_user and message.from_user.is_self

    async def status_msg(text: str) -> Message:
        if is_me:
            return await message.edit_text(text)
        return await message.reply_text(text)

    # ══════════════════════════════════════════════════════
    # 1. ШАЗАМ — ответ на медиа-сообщение
    # ══════════════════════════════════════════════════════
    if low in (".shazam", "шазам", "shazam"):
        target = message.reply_to_message
        if not target or not (
            target.video or target.audio or target.voice
            or target.video_note or target.document
        ):
            await message.reply_text("👉 **Ответь этой командой на видео, аудио или голосовое!**")
            return

        status = await status_msg("🎧 **Слушаю трек...**")
        file_path = None
        try:
            file_path = await client.download_media(target)
            if not file_path:
                await status.edit_text("❌ Не удалось скачать файл для анализа")
                return

            try:
                out = await shazam.recognize(file_path)
            except AttributeError:
                out = await shazam.recognize_song(file_path)

            if not out or 'track' not in out:
                await status.edit_text("🤷 **Shazam не смог узнать этот трек**")
            else:
                track = out['track']
                title    = track.get('title', 'Без названия')
                subtitle = track.get('subtitle', 'Неизвестный исполнитель')
                url      = track.get('url', '')
                await status.edit_text(
                    f"🎵 **Нашёл трек!**\n\n"
                    f"**Название:** `{title}`\n"
                    f"**Исполнитель:** `{subtitle}`\n\n"
                    f"[🔗 Открыть в Shazam]({url})",
                    disable_web_page_preview=True,
                )
        except Exception as e:
            logger.error(f"Shazam error: {e}")
            await status.edit_text(f"❌ **Ошибка Shazam:** {parse_ytdlp_error(e)}")
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        return

    # ══════════════════════════════════════════════════════
    # 2. МУЗЫКА — SoundCloud (не YouTube!)
    #    Команды: .music <запрос>  |  музыка <запрос>
    # ══════════════════════════════════════════════════════
    query = extract_query(raw, [".music", "музыка", ".MUSIC", "МУЗЫКА"])
    if query is not None and low.startswith((".music", "музыка")):
        if not query:
            await message.reply_text("👉 Укажи название трека: `.music Артист — Трек`")
            return

        status = await status_msg("🔍 **Ищу на SoundCloud...**")
        file_path = None
        try:
            loop = asyncio.get_running_loop()
            file_path, title, duration, artist = await loop.run_in_executor(
                None, download_audio_soundcloud, query
            )
            await status.edit_text("📤 **Отправляю трек...**")
            await client.send_audio(
                chat_id=message.chat.id,
                audio=file_path,
                title=title,
                performer=artist,
                duration=duration,
                reply_to_message_id=message.id if not is_me else None,
            )
            await status.delete()
        except Exception as e:
            logger.error(f"Music error: {e}")
            reason = parse_ytdlp_error(e)
            await status.edit_text(f"❌ **Не удалось найти трек**\n└ {reason}")
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        return

    # ══════════════════════════════════════════════════════
    # 3. ПОИСК ВИДЕО на YouTube по запросу
    #    Команда: .video <запрос>
    # ══════════════════════════════════════════════════════
    video_query = extract_query(raw, [".video", ".VIDEO"])
    if video_query is not None and low.startswith(".video"):
        if not video_query:
            await message.reply_text("👉 Укажи запрос: `.video funny cats`")
            return

        status = await status_msg(f"🔍 **Ищу на YouTube:** `{video_query}`...")
        file_path = None
        try:
            loop = asyncio.get_running_loop()
            file_path, title, duration, yt_url = await loop.run_in_executor(
                None, search_and_download_video, video_query
            )
            await status.edit_text("📤 **Загружаю в Telegram...**")
            await client.send_video(
                chat_id=message.chat.id,
                video=file_path,
                caption=f"🎬 **{title}**\n[▶️ YouTube]({yt_url})",
                duration=duration,
                supports_streaming=True,
                reply_to_message_id=message.id if not is_me else None,
            )
            await status.delete()
        except Exception as e:
            logger.error(f"Video search error: {e}")
            reason = parse_ytdlp_error(e)
            await status.edit_text(f"❌ **Не удалось найти видео**\n└ {reason}")
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        return

    # ══════════════════════════════════════════════════════
    # 4. АВТО-СКАЧИВАНИЕ ВИДЕО по прямой ссылке
    # ══════════════════════════════════════════════════════
    if "http" in low:
        SUPPORTED = [
            "youtube.com", "youtu.be",
            "tiktok.com", "instagram.com",
            "rutube.ru", "x.com", "twitter.com",
            "vk.com", "ok.ru",
        ]
        if not any(d in low for d in SUPPORTED):
            return

        url = next((w for w in raw.split() if w.startswith("http")), None)
        if not url:
            return

        status = await status_msg("⏳ **Скачиваю видео...**")
        file_path = None
        try:
            loop = asyncio.get_running_loop()
            file_path, title, duration = await loop.run_in_executor(
                None, download_video, url
            )
            await status.edit_text("📤 **Загружаю в Telegram...**")
            await client.send_video(
                chat_id=message.chat.id,
                video=file_path,
                caption=f"🎬 **{title}**",
                duration=duration,
                supports_streaming=True,
                reply_to_message_id=message.id if not is_me else None,
            )
            await status.delete()
        except Exception as e:
            logger.error(f"Video download error: {e}")
            reason = parse_ytdlp_error(e)
            await status.edit_text(f"❌ **Не удалось скачать видео**\n└ {reason}")
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)


if __name__ == "__main__":
    print("🚀 UserBot запущен! Команды: .music | .video | .shazam | авто-ссылки")
    app.run()
