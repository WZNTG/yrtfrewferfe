import os
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
import yt_dlp

# --- КОНФИГУРАЦИЯ ---
API_ID = 26526978  # Ваш API ID
API_HASH = "869a19455331f4a47535b44d371d3780" # Ваш API HASH
BOT_TOKEN = "8785733228:AAFuSfyvY8vFsN9TzCH1Ix2sfmCMv_hcUNE"
DOWNLOAD_DIR = "downloads"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Инициализация клиента Pyrogram в режиме бота
app = Client(
    "video_downloader_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

def download_video(url: str):
    """Скачивает видео в лучшем качестве без ограничений по размеру."""
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
        
        # Исправляем расширение, если yt-dlp изменил его при склейке
        if not os.path.exists(filename):
            base, _ = os.path.splitext(filename)
            if os.path.exists(base + ".mp4"):
                filename = base + ".mp4"
                
        return filename, info.get('title', 'Video'), info.get('duration', 0)

@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    await message.reply_text(
        "🚀 **Бот на Pyrogram запущен!**\n\n"
        "Теперь лимита в 50 МБ нет. Я могу отправлять видео до **2 ГБ**.\n"
        "Просто пришли мне ссылку на видео."
    )

@app.on_message(filters.text & filters.private)
async def handle_message(client: Client, message: Message):
    url = message.text
    if not url.startswith(("http://", "https://")):
        return

    status = await message.reply_text("⏳ Начинаю загрузку видео в лучшем качестве...")
    
    file_path = None
    try:
        # Запускаем загрузку в отдельном потоке, чтобы не блокировать бота
        loop = asyncio.get_running_loop()
        file_path, title, duration = await loop.run_in_executor(None, download_video, url)
        
        file_size = os.path.getsize(file_path) / (1024 * 1024)
        await status.edit_text(f"📤 Файл готов ({round(file_size, 1)} МБ). Начинаю отправку в Telegram...")

        # Отправляем видео
        await client.send_video(
            chat_id=message.chat.id,
            video=file_path,
            caption=f"🎬 **{title}**",
            duration=duration,
            supports_streaming=True,
            progress=progress_bar,
            progress_args=(status, "Отправка")
        )
        
        await status.delete()
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await status.edit_text(f"❌ Произошла ошибка: {str(e)[:100]}")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

async def progress_bar(current, total, status_message, action):
    """Функция для отображения прогресса загрузки в чате."""
    percentage = current * 100 / total
    try:
        # Обновляем сообщение раз в несколько секунд, чтобы избежать флуда
        if int(percentage) % 15 == 0:
            await status_message.edit_text(f"📤 {action}: {round(percentage, 1)}%")
    except:
        pass

if __name__ == "__main__":
    print("Бот запущен!")
    app.run()
