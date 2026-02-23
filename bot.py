import os
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from dotenv import load_dotenv
import yt_dlp

# Загружаем переменные из файла .env
load_dotenv()

# --- КОНФИГУРАЦИЯ (теперь берется из файла) ---
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
DOWNLOAD_DIR = "downloads"

# Проверка, что все данные загружены
if not all([API_ID, API_HASH, BOT_TOKEN]):
    print("❌ ОШИБКА: Данные в .env файле отсутствуют или заполнены неверно!")
    exit()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Инициализация клиента Pyrogram
app = Client(
    "video_downloader_bot",
    api_id=int(API_ID),
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

def download_video(url: str):
    file_template = os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s")
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': file_template,
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        if not os.path.exists(filename):
            base, _ = os.path.splitext(filename)
            if os.path.exists(base + ".mp4"):
                filename = base + ".mp4"
        return filename, info.get('title', 'Video'), info.get('duration', 0)

async def progress_bar(current, total, status_message, action):
    try:
        percentage = current * 100 / total
        if int(percentage) % 15 == 0:
            await status_message.edit_text(f"📤 {action}: {round(percentage, 1)}%")
    except:
        pass

@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    await message.reply_text("🚀 Бот на Pyrogram готов! Пришли ссылку.")

@app.on_message(filters.text & filters.private)
async def handle_message(client: Client, message: Message):
    url = message.text
    if not url.startswith("http"): return

    status = await message.reply_text("⏳ Загрузка видео...")
    file_path = None
    try:
        loop = asyncio.get_running_loop()
        file_path, title, duration = await loop.run_in_executor(None, download_video, url)
        
        await status.edit_text("📤 Отправка в Telegram...")

        await client.send_video(
            chat_id=message.chat.id,
            video=file_path,
            caption=f"🎬 {title}",
            duration=duration,
            supports_streaming=True,
            progress=progress_bar,
            progress_args=(status, "Загрузка")
        )
        await status.delete()
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await status.edit_text(f"❌ Ошибка: {str(e)[:50]}")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

if __name__ == "__main__":
    app.run()
