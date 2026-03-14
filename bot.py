import os
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from dotenv import load_dotenv
import yt_dlp
from shazamio import Shazam

try:
    from static_ffmpeg import add_paths
    add_paths()
except ImportError:
    pass

load_dotenv()

API_ID   = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not API_ID or not API_HASH:
    raise RuntimeError("❌ API_ID или API_HASH не заданы в .env файле!")

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Client(
    "my_user_session",
    api_id=int(API_ID),
    api_hash=API_HASH,
    workdir=".",
    sleep_threshold=60,
    max_concurrent_transmissions=5,
)

shazam = Shazam()

MAX_FILE_BYTES = 500 * 1024 * 1024  # 500 МБ

# ─── Качество ──────────────────────────────────────────────────────────────────
# Ключ → (название, формат yt-dlp)
QUALITIES = {
    "1": ("📱 360p",  "bestvideo[height<=360]+bestaudio/best[height<=360]/best"),
    "2": ("🖥  720p",  "bestvideo[height<=720]+bestaudio/best[height<=720]/best"),
    "3": ("🎬 1080p", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"),
    "4": ("💎 Макс.", "bestvideo+bestaudio/best"),
    "5": ("🎵 MP3",   "bestaudio/best"),
}

QUALITY_MENU = (
    "🎚 **Выбери качество** — ответь цифрой:\n\n"
    "1 — 📱 360p   (быстро, маленький файл)\n"
    "2 — 🖥  720p   (баланс)\n"
    "3 — 🎬 1080p  (высокое качество)\n"
    "4 — 💎 Максимальное качество\n"
    "5 — 🎵 Только аудио (MP3)"
)

# pending[chat_id] = {"mode": "dl"/"yt", "target": str, "ask_id": int}
pending: dict[int, dict] = {}


# ─── yt-dlp скачивание ─────────────────────────────────────────────────────────
def _ydl_opts(fmt: str, is_audio: bool = False) -> dict:
    opts = {
        "outtmpl":              os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
        "noplaylist":           True,
        "quiet":                True,
        "no_warnings":          True,
        "format":               fmt,
        "concurrent_fragment_downloads": 4,
        "retries":              5,
        "fragment_retries":     5,
    }
    if is_audio:
        opts["postprocessors"] = [{
            "key":              "FFmpegExtractAudio",
            "preferredcodec":   "mp3",
            "preferredquality": "192",
        }]
    else:
        opts["merge_output_format"] = "mp4"
    return opts


def _extract(info: dict, ydl, is_audio: bool) -> tuple:
    """Достаём имя файла, title, duration из info dict."""
    if "entries" in info and info["entries"]:
        info = info["entries"][0]
    filename = ydl.prepare_filename(info)
    if is_audio:
        filename = os.path.splitext(filename)[0] + ".mp3"
    else:
        # yt-dlp мог поменять расширение
        if not os.path.exists(filename):
            base = os.path.splitext(filename)[0]
            for ext in (".mp4", ".mkv", ".webm"):
                if os.path.exists(base + ext):
                    filename = base + ext
                    break
    sz = os.path.getsize(filename) if os.path.exists(filename) else 0
    if sz > MAX_FILE_BYTES:
        raise ValueError(
            f"Файл слишком большой: {sz // (1024*1024)} МБ "
            f"(макс. {MAX_FILE_BYTES // (1024*1024)} МБ) — выбери качество пониже"
        )
    return filename, info.get("title", "Без названия"), info.get("duration", 0)


def dl_video(url: str, quality_key: str) -> tuple:
    """Скачать видео/аудио по прямой ссылке."""
    _, fmt  = QUALITIES[quality_key]
    is_audio = quality_key == "5"
    opts = _ydl_opts(fmt, is_audio)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return _extract(info, ydl, is_audio)


def dl_search_yt(query: str, quality_key: str) -> tuple:
    """Найти на YouTube и скачать."""
    _, fmt   = QUALITIES[quality_key]
    is_audio = quality_key == "5"
    opts = _ydl_opts(fmt, is_audio)
    opts["default_search"] = "ytsearch"
    opts["max_downloads"]  = 1
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=True)
        if "entries" in info and info["entries"]:
            vid_id = info["entries"][0].get("id", "")
        else:
            vid_id = info.get("id", "")
        filename, title, duration = _extract(info, ydl, is_audio)
        return filename, title, duration, f"https://youtu.be/{vid_id}"


def dl_soundcloud(query: str) -> tuple:
    """Найти трек на SoundCloud и скачать как MP3."""
    opts = _ydl_opts("bestaudio/best", is_audio=True)
    opts["default_search"] = "scsearch"
    opts["max_downloads"]  = 1
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=True)
        if "entries" in info and info["entries"]:
            info = info["entries"][0]
        filename = os.path.splitext(ydl.prepare_filename(info))[0] + ".mp3"
        return (
            filename,
            info.get("title", "Без названия"),
            info.get("duration", 0),
            info.get("uploader", ""),
        )


# ─── Расшифровка ошибок ────────────────────────────────────────────────────────
def friendly_error(e: Exception) -> str:
    s = str(e)
    low = s.lower()
    if "not supported between" in low:   return "🔧 Ошибка форматов yt-dlp — попробуй другое качество"
    if "private video"         in low:   return "🔒 Видео приватное"
    if "members-only"          in low:   return "👥 Только для участников канала"
    if "age" in low and "restrict" in low: return "🔞 Возрастное ограничение"
    if "copyright" in low or "removed" in low: return "©️ Удалено по авторским правам"
    if "unavailable" in low or "not available" in low: return "🌍 Видео недоступно в этом регионе"
    if "404" in low or "not found" in low: return "🔍 Не найдено (404)"
    if "403" in low or "forbidden" in low: return "🚫 Доступ запрещён (403)"
    if "429" in low or "too many" in low: return "⏳ Слишком много запросов — подожди минуту"
    if "unsupported url" in low or "unable to extract" in low: return "🔗 Неподдерживаемая ссылка"
    if "sign in" in low or "login" in low: return "🔑 Нужна авторизация на платформе"
    if "is a live stream" in low or "live" in low: return "📡 Прямые трансляции нельзя скачать"
    if "no matching formats" in low or "no formats" in low: return "📦 Нет форматов — попробуй другое качество"
    if "ffmpeg" in low:                  return "🔧 Ошибка FFmpeg — проверь установку"
    if "network" in low or "timeout" in low or "connection" in low: return "🌐 Ошибка сети"
    if "no results" in low or "no video" in low: return "🔍 По запросу ничего не найдено"
    if "слишком большой" in low:         return s
    # вернуть первую строку оригинала
    return f"⚠️ {s.splitlines()[0][:100]}"


# ─── Таймер прогресса ──────────────────────────────────────────────────────────
async def progress_timer(msg: Message, stage: str, stop: asyncio.Event):
    icons = ["⏳", "⌛"]
    elapsed = 0
    i = 0
    while not stop.is_set():
        await asyncio.sleep(10)
        if stop.is_set():
            break
        elapsed += 10
        m, s = divmod(elapsed, 60)
        t = f"{m}м {s}с" if m else f"{s}с"
        try:
            await msg.edit_text(f"{icons[i % 2]} **{stage}**\n└ Прошло: `{t}`")
        except Exception:
            pass
        i += 1


# ─── Отправить файл в Telegram ─────────────────────────────────────────────────
async def tg_upload(client: Client, status: Message, filename: str,
                    title: str, duration: int, caption: str,
                    reply_id: int | None, is_audio: bool = False, artist: str = ""):
    stop = asyncio.Event()
    task = asyncio.create_task(progress_timer(status, "Загружаю в Telegram...", stop))
    try:
        if is_audio:
            await client.send_audio(
                chat_id=status.chat.id,
                audio=filename,
                title=title,
                performer=artist,
                duration=duration,
                reply_to_message_id=reply_id,
            )
        else:
            await client.send_video(
                chat_id=status.chat.id,
                video=filename,
                caption=caption,
                duration=duration,
                supports_streaming=True,
                reply_to_message_id=reply_id,
            )
    finally:
        stop.set()
        await task


# ─── Полный цикл: скачать + отправить ─────────────────────────────────────────
async def process_download(client: Client, status: Message,
                           mode: str, target: str, quality_key: str,
                           reply_id: int | None):
    label, _ = QUALITIES[quality_key]
    is_audio = quality_key == "5"
    fp = None
    yt_url = ""
    artist = ""

    stop  = asyncio.Event()
    timer = asyncio.create_task(progress_timer(status, f"Скачиваю {label}...", stop))

    try:
        loop = asyncio.get_running_loop()

        if mode == "dl":
            fp, title, duration = await loop.run_in_executor(
                None, dl_video, target, quality_key
            )
        elif mode == "yt":
            if is_audio:
                fp, title, duration, artist = await loop.run_in_executor(
                    None, dl_soundcloud, target
                )
            else:
                fp, title, duration, yt_url = await loop.run_in_executor(
                    None, dl_search_yt, target, quality_key
                )

        stop.set()
        await timer

        caption = f"🎬 **{title}**"
        if yt_url:
            caption += f"\n[▶️ YouTube]({yt_url})"

        await status.edit_text("📤 **Загружаю в Telegram...**")
        await tg_upload(
            client, status, fp, title, duration, caption,
            reply_id=reply_id, is_audio=is_audio, artist=artist,
        )
        await status.delete()

    except Exception as e:
        stop.set()
        logger.error(f"Download error [{mode}|{label}]: {e}", exc_info=True)
        await status.edit_text(f"❌ **Не удалось скачать**\n└ {friendly_error(e)}")
    finally:
        if fp and os.path.exists(fp):
            os.remove(fp)


# ══════════════════════════════════════════════════════════════════════════════
# ОБРАБОТЧИК СООБЩЕНИЙ
# ══════════════════════════════════════════════════════════════════════════════
SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be", "tiktok.com", "instagram.com",
    "rutube.ru", "x.com", "twitter.com", "vk.com", "ok.ru",
]


@app.on_message(filters.text & ~filters.bot)
async def on_message(client: Client, message: Message):
    if not message.text:
        return

    raw     = message.text.strip()
    low     = raw.lower()
    is_me   = bool(message.from_user and message.from_user.is_self)
    chat_id = message.chat.id

    async def reply(text: str, **kw) -> Message:
        if is_me:
            return await message.edit_text(text, **kw)
        return await message.reply_text(text, **kw)

    # ── Ожидаем выбор качества (цифра 1-5) ─────────────────────────────────
    if chat_id in pending and raw in QUALITIES:
        p = pending.pop(chat_id)
        label, _ = QUALITIES[raw]

        try:
            await client.delete_messages(chat_id, p["ask_id"])
        except Exception:
            pass

        status = await reply(f"⏳ **Начинаю:** {label}...")
        await process_download(
            client, status,
            mode=p["mode"], target=p["target"], quality_key=raw,
            reply_id=message.id if not is_me else None,
        )
        return

    # ── 1. ШАЗАМ ────────────────────────────────────────────────────────────
    if low in (".shazam", "шазам", "shazam"):
        target = message.reply_to_message
        if not target or not (target.video or target.audio or target.voice
                              or target.video_note or target.document):
            await message.reply_text(
                "👉 **Ответь этой командой на видео, аудио или голосовое!**"
            )
            return

        status = await reply("🎧 **Слушаю трек...**")
        fp = None
        try:
            fp = await client.download_media(target)
            if not fp:
                await status.edit_text("❌ Не удалось скачать файл")
                return
            try:
                out = await shazam.recognize(fp)
            except AttributeError:
                out = await shazam.recognize_song(fp)

            if not out or "track" not in out:
                await status.edit_text("🤷 **Shazam не смог узнать трек**")
            else:
                tr = out["track"]
                await status.edit_text(
                    f"🎵 **Нашёл!**\n\n"
                    f"**Название:** `{tr.get('title', '?')}`\n"
                    f"**Исполнитель:** `{tr.get('subtitle', '?')}`\n\n"
                    f"[🔗 Shazam]({tr.get('url', '')})",
                    disable_web_page_preview=True,
                )
        except Exception as e:
            logger.error(f"Shazam: {e}")
            await status.edit_text(f"❌ **Ошибка:** {friendly_error(e)}")
        finally:
            if fp and os.path.exists(fp):
                os.remove(fp)
        return

    # ── 2. МУЗЫКА — .music / музыка ─────────────────────────────────────────
    for cmd in (".music ", "музыка ", ".MUSIC ", "МУЗЫКА "):
        if low.startswith(cmd.lower()):
            q = raw[len(cmd):].strip()
            break
    else:
        q = None

    if q is not None:
        if not q:
            await message.reply_text("👉 Укажи название: `.music Исполнитель — Трек`")
            return

        status = await reply("🔍 **Ищу на SoundCloud...**")
        fp = None
        stop  = asyncio.Event()
        timer = asyncio.create_task(progress_timer(status, "Скачиваю трек...", stop))
        try:
            loop = asyncio.get_running_loop()
            fp, title, duration, artist = await loop.run_in_executor(None, dl_soundcloud, q)
            stop.set(); await timer

            await status.edit_text("📤 **Отправляю трек...**")
            await tg_upload(
                client, status, fp, title, duration, "",
                reply_id=message.id if not is_me else None,
                is_audio=True, artist=artist,
            )
            await status.delete()
        except Exception as e:
            stop.set()
            logger.error(f"Music: {e}")
            await status.edit_text(f"❌ **Не удалось найти трек**\n└ {friendly_error(e)}")
        finally:
            if fp and os.path.exists(fp):
                os.remove(fp)
        return

    # ── 3. ПОИСК НА YOUTUBE — .video ────────────────────────────────────────
    if low.startswith(".video ") or low.startswith(".video\n"):
        vq = raw[7:].strip()
        if not vq:
            await message.reply_text("👉 Укажи запрос: `.video название видео`")
            return
        ask = await message.reply_text(
            f"🔍 **YouTube:** `{vq}`\n\n{QUALITY_MENU}"
        )
        pending[chat_id] = {"mode": "yt", "target": vq, "ask_id": ask.id}
        return

    # ── 4. АВТО-СКАЧИВАНИЕ ПО ССЫЛКЕ ────────────────────────────────────────
    if "http" in low:
        if not any(d in low for d in SUPPORTED_DOMAINS):
            return
        url = next((w for w in raw.split() if w.startswith("http")), None)
        if not url:
            return

        ask = await message.reply_text(
            f"🎬 **Скачать видео?**\n\n{QUALITY_MENU}",
            disable_web_page_preview=True,
        )
        pending[chat_id] = {"mode": "dl", "target": url, "ask_id": ask.id}
        return


if __name__ == "__main__":
    print("🚀 UserBot запущен! Команды: .music | .video | .shazam | авто-ссылки")
    app.run()
