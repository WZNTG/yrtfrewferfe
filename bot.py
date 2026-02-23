import os
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from dotenv import load_dotenv
import yt_dlp

# Загружаем переменные из .env
load_dotenv()

# Настройки для UserBot (ТОЛЬКО API_ID и API_HASH)
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
DOWNLOAD_DIR = "downloads"

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Инициализируем клиента ТОЛЬКО с ID и HASH для работы как аккаунт
# Мы убрали bot_token, чтобы не было ошибки авторизации бота
app = Client(
    "my_user_session", 
    api_id=int(API_ID) if API_ID else None, 
    api_hash=API_HASH
)

def download_video(url: str):
    """Скачивание видео через yt-dlp в лучшем качестве."""
    file_template = os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s")
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': file_template,
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        
        # Если формат изменился в процессе сборки
        if not os.path.exists(filename):
            base, _ = os.path.splitext(filename)
            if os.path.exists(base + ".mp4"):
                filename = base + ".mp4"
                
        return filename, info.get('title', 'Video'), info.get('duration', 0)

@app.on_message(filters.me & filters.text)
async def handle_user_video(client: Client, message: Message):
    """Реагирует только на ваши сообщения со ссылками."""
    url = message.text
    if not url.startswith(("http://", "https://")):
        return

    # Проверка на популярные видеохостинги
    if not any(x in url for x in ["youtube", "youtu.be", "tiktok", "instagram", "rutube"]):
        return

    status = await message.edit_text("⏳ **UserBot: Загружаю видео...**")
    
    file_path = None
    try:
        # Запуск скачивания
        loop = asyncio.get_running_loop()
        file_path, title, duration = await loop.run_in_executor(None, download_video, url)
        
        await status.edit_text("📤 **Видео на сервере. Отправляю в Telegram (без лимита 50МБ)...**")

        # Отправка видео
        await client.send_video(
            chat_id=message.chat.id,
            video=file_path,
            caption=f"🎬 **{title}**",
            duration=duration,
            supports_streaming=True
        )
        
        await status.delete()
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await status.edit_text(f"❌ **Ошибка скачивания:**\n`{str(e)[:100]}`")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

if __name__ == "__main__":
    print("Запуск UserBot... Следуйте инструкциям в терминале для входа в аккаунт.")
    app.run()
