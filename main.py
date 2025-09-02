import os
import asyncio
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from fastapi import FastAPI

# ==== конфиг ====
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

PRICE_RUB = int(os.getenv("PRICE_RUB", "1499"))
PERIOD_DAYS = int(os.getenv("PERIOD_DAYS", "30"))
PAYMENT_URL = os.getenv("PAYMENT_URL", "https://tubecomy.com/pay")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "sashablogerr")

# ==== aiogram ====
bot = Bot(BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

def main_menu() -> InlineKeyboardMarkup:
    btn_join = InlineKeyboardButton(
        text=f"ВСТУПИТЬ — {PRICE_RUB} ₽ / {PERIOD_DAYS} дней",
        url=PAYMENT_URL  # после одобрения YooKassa подставишь ссылку чекаута
    )
    btn_inside = InlineKeyboardButton(text="Что внутри?", callback_data="what_inside")
    btn_support = InlineKeyboardButton(text="Задать вопрос", url=f"https://t.me/{SUPPORT_USERNAME}")
    return InlineKeyboardMarkup(inline_keyboard=[[btn_join],[btn_inside, btn_support]])

WELCOME_TEXT = (
    "<b>TubeComy</b>\n"
    "Платформа для развития и заработка на YouTube\n\n"
    "🔒 <b>Закрытое сообщество</b>: материалы, разборы и поддержка команды.\n"
    f"💳 Подписка: <b>{PRICE_RUB} ₽</b> / {PERIOD_DAYS} дней\n\n"
    "Выберите действие 👇"
)

INSIDE_TEXT = (
    "<b>Что внутри сообщества TubeComy</b>\n\n"
    "• Практические материалы по росту YouTube-каналов\n"
    "• Контент-стратегии, упаковка и продакшн\n"
    "• Идеи и рабочие подходы к монетизации\n"
    "• Обновления и поддержка участников\n\n"
    f"Подписка: <b>{PRICE_RUB} ₽</b> / {PERIOD_DAYS} дней"
)

@dp.message(CommandStart())
async def on_start(m: Message):
    await m.answer(WELCOME_TEXT, reply_markup=main_menu())

@dp.callback_query(F.data == "what_inside")
async def on_inside(cb):
    await cb.message.answer(INSIDE_TEXT, reply_markup=main_menu())
    await cb.answer()

@dp.message()
async def fallback(m: Message):
    await m.answer("Выберите действие ниже 👇", reply_markup=main_menu())

# ==== FastAPI для Render ====
app = FastAPI(title="TubeComy Bot")

@app.get("/healthz")
async def health():
    return {"status": "ok"}

_polling_task: asyncio.Task | None = None

@app.on_event("startup")
async def _on_startup():
    global _polling_task
    # запускаем long-polling параллельно веб-серверу
    async def _poll():
        await dp.start_polling(bot)
    _polling_task = asyncio.create_task(_poll())

@app.on_event("shutdown")
async def _on_shutdown():
    global _polling_task
    if _polling_task:
        _polling_task.cancel()
    await bot.session.close()

# локальный запуск: uvicorn main:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
