import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, Update, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://127.0.0.1:8000")

assert BOT_TOKEN, "Нет BOT_TOKEN в .env"
assert CHANNEL_ID != 0, "Нет CHANNEL_ID в .env"

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

@dp.message(Command("start"))
async def start_cmd(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1499₽ / 30 дней", callback_data="buy:monthly")]
    ])
    await m.answer("Привет👋 Оформи доступ к приватному каналу👇", reply_markup=kb)

@dp.callback_query(F.data.startswith("buy:"))
async def buy_plan(cq):
    await cq.message.answer("Оплату через Lava подключим на следующем этапе.")
    await cq.answer()

@app.post("/webhooks/telegram")
async def telegram_webhook(request: Request):
    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
