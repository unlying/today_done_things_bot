import asyncio
import logging
import os
from datetime import datetime

import gspread
from aiogram import Bot, Dispatcher, html
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from oauth2client.service_account import ServiceAccountCredentials

# --- Конфигурация ---
# Токен и путь к ключу Google теперь берем из переменных окружения Render
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CREDS_FILE = "/etc/secrets/credentials.json" # Имя файла, который вы загрузите в репозиторий
SHEET_NAME = "Work Log" # Ваше название таблицы
# Render автоматически подставит ваш URL, но мы можем задать путь
WEBHOOK_PATH = "/webhook"
# Порт, который дает Render
PORT = int(os.environ.get("PORT", 8080))

# --- Авторизация в Google Sheets ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open(SHEET_NAME).sheet1

# --- Инициализация бота ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    await message.answer(f"Привет, {html.bold(message.from_user.full_name)}! Пиши сюда, что сделал.")

@dp.message()
async def log_handler(message: Message) -> None:
    text = message.text
    if not text:
        return
    now = datetime.now()
    try:
        sheet.append_row([now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), text])
        await message.answer(f"✅ Записал: {text}")
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await message.answer("❌ Ошибка записи.")

# --- Настройка для Render (Webhook + Keep-Alive) ---
async def on_startup(bot: Bot):
    # Устанавливаем вебхук, используя URL, который предоставит Render
    # RENDER_EXTERNAL_URL — это переменная, которую Render создает автоматически
    base_url = os.environ.get("RENDER_EXTERNAL_URL")
    if base_url:
        await bot.set_webhook(f"{base_url}{WEBHOOK_PATH}")

async def health_check(request):
    # Этот эндпоинт нужен, чтобы Render видел, что сервис жив
    return web.Response(text="Bot is alive")

def main():
    dp.startup.register(on_startup)
    app = web.Application()
    
    # Регистрируем обработчик вебхука
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    
    # Регистрируем health check
    app.router.add_get("/", health_check)
    
    setup_application(app, dp, bot=bot)
    
    # Запускаем сервер
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
