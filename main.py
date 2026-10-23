import asyncio
import logging
import os
from datetime import datetime, timedelta

import gspread
from aiogram import Bot, Dispatcher, html
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from google import genai
from google.genai import types
from oauth2client.service_account import ServiceAccountCredentials

# --- Конфигурация ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
YOUR_CHAT_ID = int(os.environ.get("YOUR_CHAT_ID", "196564651"))

CREDS_FILE = "/etc/secrets/credentials.json"
if not os.path.exists(CREDS_FILE):
    CREDS_FILE = "credentials.json"
SHEET_NAME = "Work Log"
WEBHOOK_PATH = "/webhook"
PORT = int(os.environ.get("PORT", 8080))

# --- Инициализация ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
client_sheets = gspread.authorize(creds)
sheet = client_sheets.open(SHEET_NAME).sheet1

client_gemini = genai.Client(api_key=GEMINI_API_KEY)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# --- Вспомогательные функции (без изменений) ---
def get_entries_for_period(days: int) -> list[str]:
    all_records = sheet.get_all_values()
    if not all_records or len(all_records) < 2:
        return []
    data_rows = all_records[1:]
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    entries = []
    for row in data_rows:
        if len(row) >= 3 and row[0] >= cutoff_date:
            entries.append(row[2])
    return entries

async def send_summary(period_name: str, days: int, prompt_template: str):
    if YOUR_CHAT_ID == 0:
        logging.warning("YOUR_CHAT_ID не установлен, саммари не отправлено.")
        return
    entries = get_entries_for_period(days)
    if not entries:
        await bot.send_message(YOUR_CHAT_ID, f"За {period_name} нет записей для саммари.")
        return
    entries_text = "\n".join(f"- {e}" for e in entries)
    prompt = prompt_template.format(entries=entries_text)
    try:
        response = client_gemini.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        summary_text = response.text
    except Exception as e:
        logging.error(f"Ошибка Gemini: {e}")
        await bot.send_message(YOUR_CHAT_ID, f"❌ Ошибка при создании саммари: {e}")
        return
    await bot.send_message(
        YOUR_CHAT_ID,
        f"<b>📊 Саммари за {period_name}</b>\n\n{summary_text}",
        parse_mode="HTML",
    )

async def daily_summary_job():
    logging.info("Запуск ежедневного саммари")
    prompt = "Сделай краткое саммари того, что было сделано сегодня, на русском языке. Записи:\n{entries}"
    await send_summary("сегодня", 1, prompt)

async def weekly_summary_job():
    logging.info("Запуск недельного саммари")
    prompt = """Ты — ассистент, который делает умное саммари по рабочему дневнику.
Ниже — список того, что пользователь сделал за неделю.
Твоя задача:
1. Сгруппируй похожие действия.
2. Если одно и то же действие повторялось несколько раз, посчитай количество и укажи его.
3. Напиши краткое, но информативное саммари на русском языке.
Пример: "выложил антонимы в appstore", "выложил в аппстор flippy cube" -> "Выложено в App Store: 2 приложения (антонимы, flippy cube)."
Записи за неделю:
{entries}

Саммари:"""
    await send_summary("неделю", 7, prompt)

# --- Обработчики бота ---
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

# --- Startup ---
async def on_startup(bot: Bot):
    base_url = os.environ.get("RENDER_EXTERNAL_URL")
    if base_url:
        await bot.set_webhook(f"{base_url}{WEBHOOK_PATH}")

async def health_check(request):
    return web.Response(text="Bot is alive")

# --- Ключевое изменение: запуск через asyncio.run() ---
async def main():
    # Планировщик запускается внутри event loop — ошибки не будет
    scheduler.add_job(daily_summary_job, "cron", hour=23, minute=0)
    scheduler.add_job(weekly_summary_job, "cron", day_of_week="sun", hour=22, minute=0)
    scheduler.start()

    dp.startup.register(on_startup)
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    app.router.add_get("/", health_check)
    setup_application(app, dp, bot=bot)

    # Запускаем веб-сервер внутри того же event loop
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"Server started on port {PORT}")
    
    # Держим event loop живым
    await asyncio.Event().wait()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
