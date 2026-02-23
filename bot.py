import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
import yt_dlp

# Включаем логирование для отслеживания возможных ошибок
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- НАСТРОЙКИ БОТА ---
BOT_TOKEN = "8785733228:AAF4XxBbhQTG6K-ibhc4yR_5c5BBgvRIAnA"  # <-- Вставь сюда свой токен от @BotFather

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def download_video(url: str) -> str:
    """
    Синхронная функция для скачивания видео через yt-dlp.
    Настроена на обход лимита Telegram API (максимум 50 МБ для ботов).
    """
    options = {
        # Ищем лучшее качество до 49 МБ. Если нет - берем самое худшее, чтобы влезть в лимит
        'format': 'best[filesize<=49M]/worst',
        'outtmpl': '%(id)s.%(ext)s',  # Имя файла будет состоять из ID видео и расширения
        'noplaylist': True,           # Не скачивать плейлисты, только одно видео
        'quiet': True,                # Отключить лишний вывод в консоль
        'no_warnings': True
    }
    
    with yt_dlp.YoutubeDL(options) as ydl:
        # Извлекаем информацию и скачиваем
        info = ydl.extract_info(url, download=True)
        # Получаем итоговое имя файла
        filename = ydl.prepare_filename(info)
        return filename

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    await message.answer(
        "👋 Привет! Я бот-загрузчик видео.\n\n"
        "Просто отправь мне ссылку на **YouTube** или **Rutube**, и я скачаю видео и пришлю его прямо сюда.\n\n"
        "*(Примечание: из-за ограничений Telegram я могу отправлять файлы только до 50 МБ, поэтому длинные видео могут быть сжаты в качестве).* "
    )

@dp.message(F.text.regexp(r'(https?://)?(www\.)?(youtube\.com|youtu\.be|rutube\.ru)/.+'))
async def process_video_url(message: types.Message):
    """Обработчик сообщений, содержащих ссылки на YouTube или Rutube"""
    url = message.text
    
    # Отправляем сообщение-статус
    status_msg = await message.answer("⏳ Начинаю загрузку... Пожалуйста, подождите.")
    
    try:
        # Поскольку yt-dlp работает синхронно и блокирует поток, 
        # мы запускаем его в отдельном потоке (executor), чтобы бот не зависал для других пользователей
        loop = asyncio.get_running_loop()
        file_path = await loop.run_in_executor(None, download_video, url)
        
        await status_msg.edit_text("📤 Видео загружено на сервер! Отправляю в чат...")
        
        # Подготавливаем файл к отправке
        video_file = FSInputFile(file_path)
        
        # Отправляем видео
        await message.answer_video(video=video_file)
        
        # Удаляем локальный файл после успешной отправки для экономии места на диске
        if os.path.exists(file_path):
            os.remove(file_path)
            
        # Удаляем сообщение со статусом
        await status_msg.delete()
        
    except Exception as e:
        logging.error(f"Ошибка при обработке {url}: {e}")
        await status_msg.edit_text(
            "❌ Произошла ошибка при скачивании.\n"
            "Возможно, видео недоступно, защищено от копирования или его размер значительно превышает лимиты Telegram."
        )

@dp.message()
async def handle_other_messages(message: types.Message):
    """Обработчик для всех остальных текстовых сообщений"""
    await message.answer("Пожалуйста, отправь мне корректную ссылку на YouTube или Rutube.")

async def main():
    """Главная функция запуска бота"""
    logging.info("Бот запущен!")
    # Удаляем вебхуки (если были) и запускаем long-polling
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Запуск асинхронного цикла
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен вручную.")