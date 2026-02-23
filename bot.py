import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import FSInputFile, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
import yt_dlp

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "8785733228:AAFuSfyvY8vFsN9TzCH1Ix2sfmCMv_hcUNE"  # <-- Вставь свой токен
ADMIN_ID = 5394084759
USERS_FILE = "users.txt"
DOWNLOAD_DIR = "downloads"

# Кэш для хранения длинных ссылок (защита от лимита Telegram в 64 байта для кнопок)
url_cache = {}

# Настройка логирования для VS Code / сервера
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Создаем папку для загрузок, если её нет
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- БАЗА ПОЛЬЗОВАТЕЛЕЙ (txt) ---
def save_user(user_id: int):
    """Сохраняет ID пользователя, если его еще нет в базе."""
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                users = set(f.read().splitlines())
        else:
            users = set()
            
        if str(user_id) not in users:
            with open(USERS_FILE, "a", encoding="utf-8") as f:
                f.write(f"{user_id}\n")
    except Exception as e:
        logger.error(f"Ошибка сохранения пользователя {user_id}: {e}")

# --- YT-DLP ЛОГИКА ---
def fetch_formats(url: str) -> tuple:
    """Анализирует видео и возвращает список доступных разрешений."""
    options = {'quiet': True, 'no_warnings': True}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title', 'Видео')
        
        resolutions = set()
        for f in info.get('formats', []):
            res = f.get('height')
            # Отбираем только форматы с видео и валидным разрешением
            if res and f.get('vcodec') != 'none':
                resolutions.add(res)
                
        # Сортируем разрешения по убыванию (например: 1080, 720, 480...)
        sorted_res = sorted(list(resolutions), reverse=True)[:5]
        return sorted_res, title

def download_video(url: str, height: int) -> str:
    """
    Скачивает видео с умным ограничением веса до 49.5 МБ.
    Если выбранное качество превышает лимит, скачивает лучшее доступное до 49.5 МБ.
    """
    file_path = os.path.join(DOWNLOAD_DIR, f"%(id)s_{height}.%(ext)s")
    
    options = {
        # Жесткая логика: ищем видео нужной высоты до 40МБ + аудио до 9МБ. 
        # Если нет - берем лучшее до 49МБ. Если совсем беда - берем самое худшее.
        'format': f'bestvideo[height<={height}][filesize<40M]+bestaudio[filesize<9M]/best[height<={height}][filesize<49M]/best[filesize<49M]/worst',
        'outtmpl': file_path,
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
    }
    
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

# --- ОБРАБОТЧИКИ СООБЩЕНИЙ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    save_user(message.from_user.id)
    await message.answer(
        "👋 Привет! Отправь мне ссылку на видео с **YouTube** или **Rutube**, "
        "и я предложу тебе выбрать качество для скачивания."
    )

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    """Скрытая рассылка (только для админа)"""
    if message.from_user.id != ADMIN_ID:
        return

    text = message.text.replace("/broadcast", "").strip()
    if not text:
        return await message.answer("⚠️ Вы не ввели текст. Формат: `/broadcast Ваш текст`", parse_mode="Markdown")

    if not os.path.exists(USERS_FILE):
        return await message.answer("⚠️ База пользователей пуста.")

    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = f.read().splitlines()

    success_count = 0
    await message.answer("🔄 Начинаю рассылку...")
    
    for user_id in users:
        try:
            # Отправляем ТОЛЬКО текст админа, без лишних приписок
            await bot.send_message(chat_id=int(user_id), text=text)
            success_count += 1
            await asyncio.sleep(0.05)  # Защита от лимитов Telegram (Flood Control)
        except Exception:
            pass  # Игнорируем пользователей, которые заблокировали бота
            
    await message.answer(f"✅ Рассылка успешно завершена!\nДоставлено: **{success_count}** пользователям.", parse_mode="Markdown")

@dp.message(F.text.regexp(r'(https?://)?(www\.)?(youtube\.com|youtu\.be|rutube\.ru)/.+'))
async def handle_url(message: types.Message):
    save_user(message.from_user.id)
    url = message.text
    
    status_msg = await message.answer("🔍 Анализирую доступное качество...")
    
    try:
        loop = asyncio.get_running_loop()
        resolutions, title = await loop.run_in_executor(None, fetch_formats, url)
        
        if not resolutions:
            return await status_msg.edit_text("❌ Не удалось найти доступные форматы для этого видео.")

        # Сохраняем ссылку в кэш, привязав к ID сообщения с кнопками
        url_cache[status_msg.message_id] = url

        # Генерируем кнопки
        builder = InlineKeyboardBuilder()
        for res in resolutions:
            builder.button(
                text=f"{res}p", 
                callback_data=f"dl_{res}"  # Короткий callback, обходящий лимит ТГ
            )
        builder.adjust(3)  # По 3 кнопки в ряд
        
        await status_msg.edit_text(
            f"🎬 **{title}**\n\nВыберите желаемое качество:", 
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка анализа {url}: {e}")
        await status_msg.edit_text("❌ Произошла ошибка при анализе ссылки.")

@dp.callback_query(F.data.startswith("dl_"))
async def process_download_callback(callback: CallbackQuery):
    height = int(callback.data.split("_")[1])
    message_id = callback.message.message_id
    
    # Достаем ссылку из кэша
    url = url_cache.get(message_id)
    if not url:
        return await callback.message.edit_text("⚠️ Эта ссылка устарела. Пожалуйста, отправьте видео заново.")
        
    await callback.message.edit_text(f"⏳ Скачиваю видео (Качество до {height}p). Пожалуйста, подождите...")
    
    file_path = None
    try:
        loop = asyncio.get_running_loop()
        file_path = await loop.run_in_executor(None, download_video, url, height)
        
        await callback.message.edit_text("📤 Видео загружено! Отправляю в чат...")
        
        video = FSInputFile(file_path)
        await callback.message.answer_video(video=video)
        await callback.message.delete()
        
    except Exception as e:
        logger.error(f"Ошибка загрузки видео: {e}")
        await callback.message.edit_text(
            "❌ Ошибка при скачивании или отправке видео. "
            "Возможно, видео слишком длинное и даже в сжатом виде превышает лимит Telegram (50 МБ)."
        )
    finally:
        # 100% гарантия очистки памяти сервера
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        # Очищаем кэш ссылок
        if message_id in url_cache:
            del url_cache[message_id]

async def main():
    logger.info("Бот успешно запущен!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
