import os
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

API_ID   = os.getenv("API_ID")
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
    max_concurrent_transmissions=5,
)

shazam = Shazam()

MAX_FILE_BYTES = 500 * 1024 * 1024  # 500 МБ

# ─── Pending: ждём выбор качества от пользователя ──────────────────────────────
# { chat_id: { "mode": "dl"|"yt", "target": str, "ask_msg_id": int } }
pending: dict[int, dict] = {}

# ─── Профили качества ──────────────────────────────────────────────────────────
QUALITY_PROFILES = {
    "1": ("360p",   "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]/best"),
    "2": ("720p",   "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best"),
    "3": ("1080p",  "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best"),
    "4": ("Макс.",  "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"),
    "5": ("MP3",    "bestaudio/best"),
}

QUALITY_MENU = (
    "🎚 **Выбери качество** (ответь цифрой):\n\n"
    "`1` — 📱 360p  (быстро, маленький файл)\n"
    "`2` — 🖥  720p  (баланс качества и скорости)\n"
    "`3` — 🎬 1080p (высокое качество)\n"
    "`4` — 💎 Макс. качество\n"
    "`5` — 🎵 Только аудио MP3\n\n"
    "_Напиши цифру от 1 до 5_"
)


# ─── Базовые опции yt-dlp с ускорением ─────────────────────────────────────────
def _base_opts(fmt: str, is_audio: bool = False) -> dict:
    opts = {
        'outtmpl':                       os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
        'noplaylist':                    True,
        'quiet':                         True,
        'no_warnings':                   True,
        'format':                        fmt,
        # ── Ускорение: параллельные фрагменты ──────────────────────────────
        'concurrent_fragment_downloads': 8,
        'buffersize':                    '16K',
        'http_chunk_size':               10485760,  # 10 МБ
        'retries':                       5,
        'fragment_retries':              5,
        # ───────────────────────────────────────────────────────────────────
    }
    if is_audio:
        opts['postprocessors'] = [{
            'key':              'FFmpegExtractAudio',
            'preferredcodec':   'mp3',
            'preferredquality': '192',
        }]
    else:
        opts['merge_output_format'] = 'mp4'
    return opts


# ─── Скачивание ────────────────────────────────────────────────────────────────
def download_video(url: str, fmt: str, is_audio: bool) -> tuple:
    opts = _base_opts(fmt, is_audio=is_audio)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if 'entries' in info and info['entries']:
            info = info['entries'][0]
        filename = ydl.prepare_filename(info)
        if is_audio:
            filename = os.path.splitext(filename)[0] + ".mp3"
        else:
            filename = _fix_ext(filename)
        _check_size(filename)
        return filename, info.get('title', 'Неизвестно'), info.get('duration', 0)


def search_yt(query: str, fmt: str, is_audio: bool) -> tuple:
    opts = _base_opts(fmt, is_audio=is_audio)
    opts['default_search'] = 'ytsearch'
    opts['max_downloads']  = 1
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=True)
        if 'entries' in info and info['entries']:
            info = info['entries'][0]
        filename = ydl.prepare_filename(info)
        if is_audio:
            filename = os.path.splitext(filename)[0] + ".mp3"
        else:
            filename = _fix_ext(filename)
        _check_size(filename)
        return (
            filename,
            info.get('title', 'Неизвестно'),
            info.get('duration', 0),
            f"https://youtu.be/{info.get('id', '')}",
        )


def download_sc(query: str) -> tuple:
    opts = _base_opts('bestaudio/best', is_audio=True)
    opts['default_search'] = 'scsearch'
    opts['max_downloads']  = 1
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=True)
        if 'entries' in info and info['entries']:
            info = info['entries'][0]
        filename = os.path.splitext(ydl.prepare_filename(info))[0] + ".mp3"
        return (
            filename,
            info.get('title', 'Неизвестно'),
            info.get('duration', 0),
            info.get('uploader', 'Неизвестно'),
        )


# ─── Утилиты ───────────────────────────────────────────────────────────────────
def _fix_ext(filename: str) -> str:
    if not os.path.exists(filename):
        base = os.path.splitext(filename)[0]
        for ext in (".mp4", ".mkv", ".webm"):
            if os.path.exists(base + ext):
                return base + ext
    return filename

def _check_size(filename: str):
    if os.path.exists(filename):
        sz = os.path.getsize(filename)
        if sz > MAX_FILE_BYTES:
            raise ValueError(
                f"Файл слишком большой: {sz // (1024*1024)} МБ "
                f"(максимум {MAX_FILE_BYTES // (1024*1024)} МБ) — выбери качество пониже"
            )

def extract_query(text: str, cmds: list) -> str | None:
    low = text.lower()
    for cmd in cmds:
        if low.startswith(cmd):
            return text[len(cmd):].strip()
    return None

def parse_err(e: Exception) -> str:
    msg = str(e).lower()
    if "private video"    in msg: return "🔒 Видео приватное"
    if "members-only"     in msg: return "👥 Только для участников канала"
    if "age" in msg and ("restrict" in msg or "confirm" in msg):
                                   return "🔞 Возрастное ограничение"
    if "copyright" in msg or "removed" in msg:
                                   return "©️ Удалено по авторским правам"
    if "not available" in msg or "unavailable" in msg:
                                   return "🌍 Недоступно в вашем регионе"
    if "404" in msg or "not found" in msg: return "🔍 Не найдено (404)"
    if "403" in msg or "forbidden" in msg: return "🚫 Доступ запрещён (403)"
    if "429" in msg or "too many"  in msg: return "⏳ Слишком много запросов — подожди"
    if "no video formats" in msg or "no formats" in msg: return "📭 Нет подходящих форматов"
    if "unable to extract" in msg or "unsupported url" in msg: return "🔗 Неподдерживаемая ссылка"
    if "sign in" in msg or "login" in msg: return "🔑 Нужна авторизация"
    if "live"             in msg: return "📡 Прямые трансляции нельзя скачать"
    if "no matching formats" in msg: return "📦 Формат не найден — попробуй другое качество"
    if "ffmpeg"           in msg: return "🔧 Ошибка FFmpeg"
    if "network" in msg or "connection" in msg or "timeout" in msg:
                                   return "🌐 Ошибка сети / таймаут"
    if "no results" in msg or "no video" in msg: return "🔍 По запросу ничего не найдено"
    if "слишком большой"  in str(e).lower(): return str(e)
    return f"⚠️ {str(e).split(chr(10))[0][:80]}"


# ─── Таймер прогресса ──────────────────────────────────────────────────────────
async def progress_timer(msg: Message, stage: str, stop: asyncio.Event):
    icons   = ["⏳", "⌛"]
    elapsed = 0
    i       = 0
    while not stop.is_set():
        await asyncio.sleep(10)
        if stop.is_set():
            break
        elapsed += 10
        m, s = divmod(elapsed, 60)
        t = f"{m}м {s}с" if m else f"{s}с"
        try:
            await msg.edit_text(f"{icons[i%2]} **{stage}**\n└ Прошло: `{t}`")
        except Exception:
            pass
        i += 1


# ─── Загрузка в Telegram с таймером ────────────────────────────────────────────
async def upload(client: Client, status: Message, fp: str,
                 title: str, duration: int, caption: str,
                 reply_id: int | None, is_audio: bool = False, artist: str = ""):
    stop = asyncio.Event()
    task = asyncio.create_task(progress_timer(status, "Загружаю в Telegram...", stop))
    try:
        if is_audio:
            await client.send_audio(
                chat_id=status.chat.id, audio=fp,
                title=title, performer=artist, duration=duration,
                reply_to_message_id=reply_id,
            )
        else:
            await client.send_video(
                chat_id=status.chat.id, video=fp,
                caption=caption, duration=duration,
                supports_streaming=True,
                reply_to_message_id=reply_id,
            )
    finally:
        stop.set()
        await task


# ─── Выполнить скачивание по выбранному качеству ───────────────────────────────
async def do_download(client: Client, status: Message, mode: str,
                      target: str, quality_key: str, reply_id: int | None):
    label, fmt = QUALITY_PROFILES[quality_key]
    is_audio   = quality_key == "5"
    fp         = None
    stop       = asyncio.Event()
    t_task     = asyncio.create_task(
        progress_timer(status, f"Скачиваю ({label})...", stop)
    )
    yt_url = ""
    artist = ""

    try:
        loop = asyncio.get_running_loop()

        if mode == "dl":
            fp, title, duration = await loop.run_in_executor(
                None, download_video, target, fmt, is_audio
            )
        else:
            # поиск на YouTube; для MP3 — SoundCloud
            if is_audio:
                fp, title, duration, artist = await loop.run_in_executor(
                    None, download_sc, target
                )
            else:
                fp, title, duration, yt_url = await loop.run_in_executor(
                    None, search_yt, target, fmt, False
                )

        stop.set(); await t_task
        await status.edit_text("📤 **Загружаю в Telegram...**")

        caption = f"🎬 **{title}**"
        if yt_url:
            caption += f"\n[▶️ YouTube]({yt_url})"

        await upload(client, status, fp, title, duration, caption,
                     reply_id=reply_id, is_audio=is_audio, artist=artist)
        await status.delete()

    except Exception as e:
        stop.set()
        logger.error(f"Download error [{mode}|{label}]: {e}")
        await status.edit_text(f"❌ **Не удалось скачать**\n└ {parse_err(e)}")
    finally:
        if fp and os.path.exists(fp):
            os.remove(fp)


# ══════════════════════════════════════════════════════════════════════════════
# ХЕНДЛЕР СООБЩЕНИЙ
# ══════════════════════════════════════════════════════════════════════════════
SUPPORTED = ["youtube.com", "youtu.be", "tiktok.com", "instagram.com",
             "rutube.ru", "x.com", "twitter.com", "vk.com", "ok.ru"]

@app.on_message(filters.text & ~filters.bot)
async def on_message(client: Client, message: Message):
    if not message.text:
        return

    raw    = message.text.strip()
    low    = raw.lower()
    is_me  = message.from_user and message.from_user.is_self
    chat_id = message.chat.id

    async def reply(text: str) -> Message:
        if is_me:
            return await message.edit_text(text)
        return await message.reply_text(text)

    # ══ Ответ на ожидание качества ════════════════════════════════════════════
    if chat_id in pending and raw in QUALITY_PROFILES:
        p       = pending.pop(chat_id)
        mode    = p["mode"]
        target  = p["target"]
        label, _ = QUALITY_PROFILES[raw]

        # Удаляем сообщение с меню если можем
        try:
            await client.delete_messages(chat_id, p["ask_msg_id"])
        except Exception:
            pass

        status = await reply(f"⏳ **Начинаю скачивание** {label}...")
        await do_download(client, status, mode, target, raw,
                          reply_id=message.id if not is_me else None)
        return

    # ══ 1. ШАЗАМ ═════════════════════════════════════════════════════════════
    if low in (".shazam", "шазам", "shazam"):
        target = message.reply_to_message
        if not target or not (target.video or target.audio or target.voice
                              or target.video_note or target.document):
            await message.reply_text("👉 **Ответь этой командой на видео, аудио или голосовое!**")
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

            if not out or 'track' not in out:
                await status.edit_text("🤷 **Shazam не смог узнать трек**")
            else:
                tr = out['track']
                await status.edit_text(
                    f"🎵 **Нашёл!**\n\n"
                    f"**Название:** `{tr.get('title','?')}`\n"
                    f"**Исполнитель:** `{tr.get('subtitle','?')}`\n\n"
                    f"[🔗 Shazam]({tr.get('url','')})",
                    disable_web_page_preview=True,
                )
        except Exception as e:
            logger.error(f"Shazam: {e}")
            await status.edit_text(f"❌ **Ошибка:** {parse_err(e)}")
        finally:
            if fp and os.path.exists(fp):
                os.remove(fp)
        return

    # ══ 2. МУЗЫКА — SoundCloud ════════════════════════════════════════════════
    q = extract_query(raw, [".music", "музыка", ".MUSIC", "МУЗЫКА"])
    if q is not None and low.startswith((".music", "музыка")):
        if not q:
            await message.reply_text("👉 Укажи название: `.music Исполнитель — Трек`")
            return

        status = await reply("🔍 **Ищу на SoundCloud...**")
        fp     = None
        stop   = asyncio.Event()
        t_task = asyncio.create_task(progress_timer(status, "Скачиваю трек...", stop))
        try:
            loop = asyncio.get_running_loop()
            fp, title, duration, artist = await loop.run_in_executor(None, download_sc, q)
            stop.set(); await t_task

            await status.edit_text("📤 **Отправляю трек...**")
            await upload(client, status, fp, title, duration, "",
                         reply_id=message.id if not is_me else None,
                         is_audio=True, artist=artist)
            await status.delete()
        except Exception as e:
            stop.set()
            logger.error(f"Music: {e}")
            await status.edit_text(f"❌ **Не удалось найти трек**\n└ {parse_err(e)}")
        finally:
            if fp and os.path.exists(fp):
                os.remove(fp)
        return

    # ══ 3. ПОИСК ВИДЕО — .video <запрос> ═════════════════════════════════════
    vq = extract_query(raw, [".video", ".VIDEO"])
    if vq is not None and low.startswith(".video"):
        if not vq:
            await message.reply_text("👉 Укажи запрос: `.video название видео`")
            return

        ask = await message.reply_text(
            f"🔍 **YouTube:** `{vq}`\n\n{QUALITY_MENU}"
        )
        pending[chat_id] = {"mode": "yt", "target": vq, "ask_msg_id": ask.id}
        return

    # ══ 4. АВТО-СКАЧИВАНИЕ ПО ССЫЛКЕ ═════════════════════════════════════════
    if "http" in low:
        if not any(d in low for d in SUPPORTED):
            return
        url = next((w for w in raw.split() if w.startswith("http")), None)
        if not url:
            return

        ask = await message.reply_text(
            f"🎬 **Скачать видео?**\n\n{QUALITY_MENU}",
            disable_web_page_preview=True,
        )
        pending[chat_id] = {"mode": "dl", "target": url, "ask_msg_id": ask.id}
        return


if __name__ == "__main__":
    print("🚀 UserBot запущен! Команды: .music | .video | .shazam | авто-ссылки")
    app.run()
