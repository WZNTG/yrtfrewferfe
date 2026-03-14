import os
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
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

# ─── Профили качества ──────────────────────────────────────────────────────────
QUALITY_PROFILES = {
    "360":   "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]/best",
    "720":   "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best",
    "1080":  "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best",
    "best":  "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
    "audio": "bestaudio/best",
}

QUALITY_LABELS = {
    "360":   "📱 360p (быстро)",
    "720":   "🖥 720p (баланс)",
    "1080":  "🎬 1080p",
    "best":  "💎 Макс.",
    "audio": "🎵 MP3",
}


# ─── Базовые опции yt-dlp — с ускорением через параллельные фрагменты ──────────
def _base_opts(fmt: str, is_audio: bool = False) -> dict:
    opts = {
        'outtmpl':                       os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
        'noplaylist':                    True,
        'quiet':                         True,
        'no_warnings':                   True,
        'format':                        fmt,
        # ── Ускорение ─────────────────────────────────────────────────────────
        'concurrent_fragment_downloads': 8,       # 8 параллельных потоков
        'buffersize':                    '16K',
        'http_chunk_size':               10485760, # 10 МБ чанки
        'retries':                       5,
        'fragment_retries':              5,
        # ──────────────────────────────────────────────────────────────────────
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


# ─── Скачивание видео по ссылке ─────────────────────────────────────────────────
def download_video(url: str, quality: str = "720") -> tuple:
    is_audio = quality == "audio"
    opts     = _base_opts(QUALITY_PROFILES[quality], is_audio=is_audio)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if 'entries' in info and info['entries']:
            info = info['entries'][0]

        filename = ydl.prepare_filename(info)
        filename = os.path.splitext(filename)[0] + ".mp3" if is_audio else _fix_ext(filename)
        _check_size(filename)
        return filename, info.get('title', 'Неизвестно'), info.get('duration', 0)


# ─── Поиск и скачивание с YouTube ───────────────────────────────────────────────
def search_yt(query: str, quality: str = "720") -> tuple:
    opts = _base_opts(QUALITY_PROFILES[quality])
    opts['default_search'] = 'ytsearch'
    opts['max_downloads']  = 1

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=True)
        if 'entries' in info and info['entries']:
            info = info['entries'][0]

        filename = _fix_ext(ydl.prepare_filename(info))
        _check_size(filename)
        return (
            filename,
            info.get('title', 'Неизвестно'),
            info.get('duration', 0),
            f"https://youtu.be/{info.get('id', '')}",
        )


# ─── Скачивание музыки с SoundCloud ─────────────────────────────────────────────
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
    if "not available"    in msg or "unavailable" in msg:
                                   return "🌍 Недоступно в вашем регионе"
    if "404"              in msg or "not found" in msg:  return "🔍 Не найдено (404)"
    if "403"              in msg or "forbidden" in msg:  return "🚫 Доступ запрещён (403)"
    if "429"              in msg or "too many"  in msg:  return "⏳ Слишком много запросов — подожди"
    if "no video formats" in msg or "no formats" in msg: return "📭 Нет подходящих форматов"
    if "unable to extract" in msg or "unsupported url" in msg: return "🔗 Неподдерживаемая ссылка"
    if "sign in" in msg or "login" in msg: return "🔑 Нужна авторизация на платформе"
    if "live"             in msg: return "📡 Прямые трансляции нельзя скачать"
    if "no matching formats" in msg: return "📦 Формат не найден — попробуй другое качество"
    if "ffmpeg"           in msg: return "🔧 Ошибка FFmpeg — проверь установку"
    if "network" in msg or "connection" in msg or "timeout" in msg:
                                   return "🌐 Ошибка сети / таймаут"
    if "no results"       in msg or "no video" in msg:  return "🔍 По запросу ничего не найдено"
    if "слишком большой"  in str(e).lower(): return str(e)
    return f"⚠️ {str(e).split(chr(10))[0][:80]}"


# ─── Таймер прогресса ──────────────────────────────────────────────────────────
async def timer(msg: Message, stage: str, stop: asyncio.Event):
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
            await msg.edit_text(f"{icons[i%2]} **{stage}**\n└ Прошло: `{t}`")
        except Exception:
            pass
        i += 1


# ─── Отправка с прогрессом ──────────────────────────────────────────────────────
async def upload(client: Client, status: Message, file_path: str,
                 title: str, duration: int, caption: str,
                 reply_id: int | None, is_audio: bool = False, artist: str = ""):
    stop  = asyncio.Event()
    task  = asyncio.create_task(timer(status, "Загружаю в Telegram...", stop))
    try:
        if is_audio:
            await client.send_audio(
                chat_id=status.chat.id, audio=file_path,
                title=title, performer=artist, duration=duration,
                reply_to_message_id=reply_id,
            )
        else:
            await client.send_video(
                chat_id=status.chat.id, video=file_path,
                caption=caption, duration=duration,
                supports_streaming=True,
                reply_to_message_id=reply_id,
            )
    finally:
        stop.set()
        await task


# ─── Кнопки выбора качества ─────────────────────────────────────────────────────
def quality_keyboard(mode: str, target: str) -> InlineKeyboardMarkup:
    t = target[:180]  # ограничиваем длину для callback_data
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(QUALITY_LABELS["360"],  callback_data=f"{mode}|360|{t}"),
            InlineKeyboardButton(QUALITY_LABELS["720"],  callback_data=f"{mode}|720|{t}"),
            InlineKeyboardButton(QUALITY_LABELS["1080"], callback_data=f"{mode}|1080|{t}"),
        ],
        [
            InlineKeyboardButton(QUALITY_LABELS["best"],  callback_data=f"{mode}|best|{t}"),
            InlineKeyboardButton(QUALITY_LABELS["audio"], callback_data=f"{mode}|audio|{t}"),
        ],
    ])


# ══════════════════════════════════════════════════════════════════════════════
# ХЕНДЛЕР СООБЩЕНИЙ
# ══════════════════════════════════════════════════════════════════════════════
SUPPORTED = ["youtube.com", "youtu.be", "tiktok.com", "instagram.com",
             "rutube.ru", "x.com", "twitter.com", "vk.com", "ok.ru"]

@app.on_message(filters.text & ~filters.bot)
async def on_message(client: Client, message: Message):
    if not message.text:
        return

    raw   = message.text.strip()
    low   = raw.lower()
    is_me = message.from_user and message.from_user.is_self

    async def reply(text: str) -> Message:
        if is_me:
            return await message.edit_text(text)
        return await message.reply_text(text)

    # ══ 1. ШАЗАМ ═══════════════════════════════════════════════════════════════
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

    # ══ 2. МУЗЫКА (SoundCloud) ══════════════════════════════════════════════════
    q = extract_query(raw, [".music", "музыка", ".MUSIC", "МУЗЫКА"])
    if q is not None and low.startswith((".music", "музыка")):
        if not q:
            await message.reply_text("👉 Укажи название: `.music Исполнитель — Трек`")
            return

        status = await reply("🔍 **Ищу на SoundCloud...**")
        fp = None
        stop_t = asyncio.Event()
        t_task = asyncio.create_task(timer(status, "Скачиваю трек...", stop_t))
        try:
            loop = asyncio.get_running_loop()
            fp, title, duration, artist = await loop.run_in_executor(None, download_sc, q)
            stop_t.set(); await t_task

            await status.edit_text("📤 **Отправляю трек...**")
            await upload(client, status, fp, title, duration, "",
                         reply_id=message.id if not is_me else None,
                         is_audio=True, artist=artist)
            await status.delete()
        except Exception as e:
            stop_t.set()
            logger.error(f"Music: {e}")
            await status.edit_text(f"❌ **Не удалось найти трек**\n└ {parse_err(e)}")
        finally:
            if fp and os.path.exists(fp):
                os.remove(fp)
        return

    # ══ 3. ПОИСК ВИДЕО — .video <запрос> ════════════════════════════════════════
    vq = extract_query(raw, [".video", ".VIDEO"])
    if vq is not None and low.startswith(".video"):
        if not vq:
            await message.reply_text("👉 Укажи запрос: `.video название видео`")
            return
        await message.reply_text(
            f"🔍 **Найти на YouTube:** `{vq}`\n\n🎚 Выбери качество:",
            reply_markup=quality_keyboard("yt", vq),
        )
        return

    # ══ 4. АВТО-СКАЧИВАНИЕ ПО ССЫЛКЕ ════════════════════════════════════════════
    if "http" in low:
        if not any(d in low for d in SUPPORTED):
            return
        url = next((w for w in raw.split() if w.startswith("http")), None)
        if not url:
            return

        await message.reply_text(
            f"🎬 **Скачать видео?**\n\n🎚 Выбери качество:",
            reply_markup=quality_keyboard("dl", url),
            disable_web_page_preview=True,
        )
        return


# ══════════════════════════════════════════════════════════════════════════════
# ХЕНДЛЕР КНОПОК КАЧЕСТВА
# ══════════════════════════════════════════════════════════════════════════════
@app.on_callback_query()
async def on_quality(client: Client, cb: CallbackQuery):
    data   = cb.data or ""
    parts  = data.split("|", 2)
    if len(parts) != 3 or parts[0] not in ("dl", "yt"):
        await cb.answer("Неизвестная кнопка", show_alert=True)
        return

    mode, quality, target = parts
    label = QUALITY_LABELS.get(quality, quality)
    is_audio = quality == "audio"

    await cb.answer(f"Начинаю скачивание {label}")
    status = cb.message
    await status.edit_text(f"⏳ **Скачиваю** {label}...")

    fp       = None
    stop_t   = asyncio.Event()
    t_task   = asyncio.create_task(timer(status, f"Скачиваю {label}...", stop_t))
    yt_url   = ""
    artist   = ""

    try:
        loop = asyncio.get_running_loop()

        if mode == "dl":
            fp, title, duration = await loop.run_in_executor(
                None, download_video, target, quality
            )
        else:
            # yt — поиск на YouTube (для audio режима — SoundCloud)
            if is_audio:
                fp, title, duration, artist = await loop.run_in_executor(
                    None, download_sc, target
                )
            else:
                fp, title, duration, yt_url = await loop.run_in_executor(
                    None, search_yt, target, quality
                )

        stop_t.set(); await t_task
        await status.edit_text("📤 **Загружаю в Telegram...**")

        caption = f"🎬 **{title}**"
        if yt_url:
            caption += f"\n[▶️ YouTube]({yt_url})"

        await upload(client, status, fp, title, duration, caption,
                     reply_id=None, is_audio=is_audio, artist=artist)
        await status.delete()

    except Exception as e:
        stop_t.set()
        logger.error(f"Quality download error [{mode}|{quality}]: {e}")
        await status.edit_text(f"❌ **Не удалось скачать**\n└ {parse_err(e)}")
    finally:
        if fp and os.path.exists(fp):
            os.remove(fp)


if __name__ == "__main__":
    print("🚀 UserBot запущен! Команды: .music | .video | .shazam | авто-ссылки")
    app.run()
