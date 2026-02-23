import os
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from dotenv import load_dotenv
import yt_dlp

# Загружаем переменные из .env
load_dotenv()

# Для аккаунта BOT_TOKEN не нужен! 
# Используем только API_ID и API_HASH
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
DOWNLOAD_DIR = "downloads"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Инициализируем клиента как "Сессия пользователя"
app = Client(
    "my_user_account", 
    api_id=int(API_ID), 
    api_hash=API_HASH
)

def download_video(url: str):
    """Скачивает видео в максимальном качестве."""
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
        
        # Если yt-dlp изменил расширение в процессе
        if not os.path.exists(filename):
            base, _ = os.path.splitext(filename)
            if os.path.exists(base + ".mp4"):
                filename = base + ".mp4"
                
        return filename, info.get('title', 'Video'), info.get('duration', 0)

@app.on_message(filters.me & filters.text)
async def handle_my_message(client: Client, message: Message):
    """
    Бот будет реагировать только на ВАШИ сообщения.
    Отправьте ссылку самому себе или в любой чат, и он начнет скачивание.
    """
    url = message.text
    if not url.startswith(("http://", "https://")):
        return

    # Список поддерживаемых сайтов (опционально)
    if not any(x in url for x in ["youtube", "youtu.be", "tiktok", "instagram", "rutube"]):
        return

    print(f"Обработка ссылки: {url}")
    
    file_path = None
    try:
        # Информируем себя о начале процесса (редактируем свое же сообщение)
        await message.edit_text("⏳ **Начинаю загрузку видео на сервер...**")
        
        loop = asyncio.get_running_loop()
        file_path, title, duration = await loop.run_in_executor(None, download_video, url)
        
        await message.edit_text("📤 **Загрузка завершена. Отправляю в Telegram...**")

        # Отправляем видео в тот же чат
        await client.send_video(
            chat_id=message.chat.id,
            video=file_path,
            caption=f"🎬 **{title}**\n\nСкачано через UserBot",
            duration=duration,
            supports_streaming=True
        )
        
        # Удаляем сервисное сообщение
        await message.delete()
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.edit_text(f"❌ **Ошибка:** {str(e)[:100]}")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

if __name__ == "__main__":
    print("UserBot запускается... Если это первый раз, следуйте инструкциям в консоли.")
    app.run()
