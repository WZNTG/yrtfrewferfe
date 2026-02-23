import os
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from dotenv import load_dotenv
import yt_dlp

# Загружаем переменные окружения
load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
DOWNLOAD_DIR = "downloads"

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Инициализируем клиента
# Имя сессии "my_user_session" должно совпадать с именем вашего файла .session
app = Client(
    "my_user_session", 
    api_id=int(API_ID) if API_ID else None, 
    api_hash=API_HASH,
    workdir="."  # Указывает искать файл сессии в текущей папке
)

def download_video(url: str):
    """Скачивание видео через yt-dlp."""
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
        
        # Проверка на случай изменения расширения (например, mkv -> mp4)
        if not os.path.exists(filename):
            base, _ = os.path.splitext(filename)
            if os.path.exists(base + ".mp4"):
                filename = base + ".mp4"
                
        return filename, info.get('title', 'Video'), info.get('duration', 0)

@app.on_message(filters.me & filters.text)
async def handle_user_video(client: Client, message: Message):
    """Бот реагирует, когда ВЫ отправляете ссылку (например, в 'Избранное')"""
    url = message.text
    if not url.startswith(("http://", "https://")):
        return

    # Список сайтов для обработки
    if not any(x in url for x in ["youtube", "youtu.be", "tiktok", "instagram", "rutube"]):
        return

    # Редактируем ваше сообщение, чтобы видеть прогресс
    status = await message.edit_text("⏳ **Начинаю скачивание (лимит 2 ГБ)...**")
    
    file_path = None
    try:
        # Качаем видео
        loop = asyncio.get_running_loop()
        file_path, title, duration = await loop.run_in_executor(None, download_video, url)
        
        await status.edit_text("📤 **Видео скачано! Загружаю в Telegram...**")

        # Отправляем видео файлом с поддержкой стриминга
        await client.send_video(
            chat_id=message.chat.id,
            video=file_path,
            caption=f"🎬 **{title}**",
            duration=duration,
            supports_streaming=True
        )
        
        # Удаляем сервисное сообщение, чтобы не мешало
        await status.delete()
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await status.edit_text(f"❌ **Ошибка:**\n`{str(e)[:100]}`")
    finally:
        # Чистим место на диске хостинга
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

if __name__ == "__main__":
    if not os.path.exists("my_user_session.session"):
        print("❌ ФАЙЛ СЕССИИ НЕ НАЙДЕН! Загрузите my_user_session.session на сервер.")
    else:
        print("✅ Сессия найдена. UserBot запускается...")
        app.run()
