import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
import yt_dlp

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "8785733228:AAFuSfyvY8vFsN9TzCH1Ix2sfmCMv_hcUNE"
ADMIN_ID = 5394084759
USERS_FILE = "users.txt"
DOWNLOAD_DIR = "downloads"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- СИСТЕМА ПОЛЬЗОВАТЕЛЕЙ ---
def save_user(user_id: int):
    try:
        users = set()
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                users = set(f.read().splitlines())
        if str(user_id) not in users:
            with open(USERS_FILE, "a", encoding="utf-8") as f:
                f.write(f"{user_id}\n")
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")

# --- ЛОГИКА ЗАГРУЗКИ ---
def download_best_video(url: str):
    """
    Скачивает видео в максимально возможном качестве до 50МБ без FFmpeg.
    """
    file_template = os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s")
    
    ydl_opts = {
        # Ищем лучший готовый формат (видео+звук), который весит меньше 50МБ.
        # Если такого нет — берем самый маленький (worst).
        'format': 'best[ext=mp4][filesize<50M]/best[filesize<50M]/worst',
        'outtmpl': file_template,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info), info.get('title', 'Video')

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    save_user(message.from_user.id)
    await message.answer("🚀 Бот готов. Пришли ссылку на видео, и я пришлю его в лучшем качестве!")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    """Скрытая рассылка: отправляет ТОЛЬКО текст админа"""
    if message.from_user.id != ADMIN_ID:
        return
    
    # Извлекаем текст после команды /broadcast
    text_to_send = message.text.replace("/broadcast", "").strip()
    
    if not text_to_send:
        return await message.answer("⚠️ Ошибка: введите текст рассылки после команды.")

    if not os.path.exists(USERS_FILE):
        return await message.answer("⚠️ База пользователей пуста.")

    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = f.read().splitlines()

    count = 0
    status = await message.answer(f"📢 Начинаю рассылку на {len(users)} чел...")
    
    for u_id in users:
        try:
            # Отправка чистого сообщения без подписей
            await bot.send_message(chat_id=int(u_id), text=text_to_send)
            count += 1
            await asyncio.sleep(0.05) # Защита от спам-фильтра
        except Exception:
            continue
            
    await status.edit_text(f"✅ Рассылка завершена. Сообщение получили {count} пользователей.")

@dp.message(F.text.regexp(r'(https?://)?(www\.)?(youtube\.com|youtu\.be|rutube\.ru)/.+'))
async def handle_video(message: types.Message):
    save_user(message.from_user.id)
    url = message.text
    status = await message.answer("⏳ Обработка видео... Ищу лучшее качество.")
    
    file_path = None
    try:
        loop = asyncio.get_running_loop()
        file_path, title = await loop.run_in_executor(None, download_best_video, url)
        
        await status.edit_text("📤 Видео загружено на сервер, отправляю тебе...")
        
        video_file = FSInputFile(file_path)
        
        # Пробуем отправить как видео (чтобы открылся плеер)
        try:
            await message.answer_video(video=video_file, caption=f"🎬 {title}")
        except Exception:
            # Если Telegram отклоняет (не тот кодек или размер на грани), шлем как файл
            await message.answer_document(document=video_file, caption=f"🎬 {title}")
            
        await status.delete()
        
    except Exception as e:
        logger.error(f"Download Error: {e}")
        await status.edit_text("❌ Ошибка: видео весит больше 50 МБ или недоступно. В текущем режиме Telegram не позволяет ботам слать файлы тяжелее 50 МБ.")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот выключен.")
