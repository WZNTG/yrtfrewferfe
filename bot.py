import os
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from dotenv import load_dotenv
import yt_dlp
from shazamio import Shazam

# Инициализация FFmpeg для корректной работы со звуком
try:
    from static_ffmpeg import add_paths
    add_paths()
except ImportError:
    pass

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
DOWNLOAD_DIR = "downloads"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

app = Client(
    "my_user_session", 
    api_id=int(API_ID) if API_ID else None, 
    api_hash=API_HASH,
    workdir=".",
    sleep_threshold=60
)

shazam = Shazam()

def download_content(url_or_search, is_audio=False):
    """Функция загрузки контента через yt-dlp"""
    file_template = os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s")
    ydl_opts = {
        'outtmpl': file_template,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
    }

    if is_audio:
        ydl_opts.update({
            'format': 'bestaudio/best',
            'default_search': 'ytsearch',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        })
    else:
        ydl_opts.update({
            'format': 'bestvideo+bestaudio/best',
            'merge_output_format': 'mp4'
        })

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url_or_search, download=True)
        # Если это результат поиска, берем первый элемент
        if 'entries' in info and info['entries']:
            info = info['entries'][0]
            
        filename = ydl.prepare_filename(info)
        
        # Фикс расширений файлов
        if is_audio:
            filename = os.path.splitext(filename)[0] + ".mp3"
        elif not os.path.exists(filename):
            base = os.path.splitext(filename)[0]
            if os.path.exists(base + ".mp4"):
                filename = base + ".mp4"
                
        return filename, info.get('title', 'Неизвестно'), info.get('duration', 0), info.get('uploader', 'Неизвестно')

@app.on_message(filters.text & (filters.private | filters.group))
async def handle_everything(client: Client, message: Message):
    # Игнорируем других ботов
    if message.from_user and message.from_user.is_bot:
        return

    text = message.text.strip().lower() if message.text else ""
    if not text:
        return

    is_me = message.from_user and message.from_user.is_self

    # ==========================================
    # 1. ЛОГИКА ШАЗАМА (Ответ на сообщение)
    # ==========================================
    if text in [".shazam", "шазам", "shazam"]:
        target = message.reply_to_message
        if not target or not (target.video or target.audio or target.voice or target.video_note or target.document):
            await message.reply_text("👉 **Ответь этой командой на видео, аудио или голосовое!**")
            return

        status = await (message.edit_text("🎧 **Слушаю трек...**") if is_me else message.reply_text("🎧 **Слушаю трек...**"))
        file_path = None
        
        try:
            file_path = await client.download_media(target)
            if not file_path:
                await status.edit_text("❌ Ошибка: не удалось скачать файл для проверки.")
                return

            # Поддержка разных версий библиотеки shazamio
            try:
                out = await shazam.recognize(file_path)
            except AttributeError:
                out = await shazam.recognize_song(file_path)
            
            if not out or 'track' not in out:
                await status.edit_text("🤷‍♂️ **Shazam не смог узнать этот трек.**")
            else:
                track = out['track']
                title = track.get('title', 'Без названия')
                subtitle = track.get('subtitle', 'Неизвестный исполнитель')
                url = track.get('url', '')
                
                text_result = f"🎵 **Нашел трек!**\n\n**Название:** `{title}`\n**Исполнитель:** `{subtitle}`\n\n[🔗 Открыть в Shazam]({url})"
                await status.edit_text(text_result, disable_web_page_preview=True)
                
        except Exception as e:
            logger.error(f"Shazam error: {e}")
            await status.edit_text(f"❌ **Ошибка Shazam:** `{str(e)[:50]}`")
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        return

    # ==========================================
    # 2. ЛОГИКА МУЗЫКИ (.music)
    # ==========================================
    if text.startswith((".music", "музыка")):
        original_text = message.text.strip()
        # Вырезаем команду из текста с учетом регистра
        for cmd in [".music", "музыка", ".MUSIC", "МУЗЫКА"]:
            if original_text.startswith(cmd):
                query = original_text.replace(cmd, "").strip()
                break
                
        if not query:
            return

        status = await (message.edit_text("🔍 **Ищу аудио...**") if is_me else message.reply_text("🔍 **Ищу аудио...**"))
        file_path = None
        
        try:
            loop = asyncio.get_running_loop()
            file_path, title, duration, artist = await loop.run_in_executor(None, download_content, query, True)
            
            await status.edit_text("📤 **Отправляю трек...**")
            await client.send_audio(
                chat_id=message.chat.id,
                audio=file_path,
                title=title,
                performer=artist,
                duration=duration,
                reply_to_message_id=message.id if not is_me else None
            )
            # Если это наше сообщение - status и есть само сообщение. Удаляем его.
            await status.delete()
        except Exception as e:
            logger.error(f"Music error: {e}")
            await status.edit_text(f"❌ **Ошибка поиска:** `{str(e)[:50]}`")
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        return

    # ==========================================
    # 3. ЛОГИКА ВИДЕО (Авто-скачивание по ссылке)
    # ==========================================
    if "http" in text:
        domains = ["youtube.com", "youtu.be", "tiktok.com", "instagram.com", "rutube.ru", "x.com", "twitter.com"]
        if not any(domain in text for domain in domains):
            return

        # Достаем саму ссылку из текста
        url = next((word for word in message.text.split() if word.startswith("http")), None)
        if not url:
            return

        status = await (message.edit_text("🚀 **Скачиваю видео...**") if is_me else message.reply_text("⏳ **Скачиваю видео...**", quote=True))
        file_path = None
        
        try:
            loop = asyncio.get_running_loop()
            file_path, title, duration, _ = await loop.run_in_executor(None, download_content, url, False)
            
            await status.edit_text("📤 **Загружаю в Telegram...**")
            await client.send_video(
                chat_id=message.chat.id,
                video=file_path,
                caption=f"🎬 **{title}**",
                duration=duration,
                supports_streaming=True,
                reply_to_message_id=message.id if not is_me else None
            )
            # Удаляем статусное сообщение (и исходное, если оно наше)
            await status.delete()
        except Exception as e:
            logger.error(f"Video error: {e}")
            await status.edit_text(f"❌ **Не удалось скачать:** `{str(e)[:50]}`")
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)

if __name__ == "__main__":
    print("🚀 UserBot (Видео + Музыка + Shazam) запущен и работает без ошибок!")
    app.run()
