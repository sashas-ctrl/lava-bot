import os
import logging
from typing import Dict, Callable, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Update, Message, CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

# ---------- ЛОГИ ----------
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("tubecomy-bot")

# ---------- КОНФИГ ----------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL")  # https://lava-bot.onrender.com
if not BOT_TOKEN or not PUBLIC_URL:
    raise RuntimeError("ENV BOT_TOKEN и PUBLIC_URL обязательны")

# ---------- BOT / DP / APP ----------
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

# ---------- ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК ----------
@dp.error()
async def on_error(event, exception):
    # логируем что и где упало
    try:
        upd_type = event.update.event_type
    except Exception:
        upd_type = "unknown"
    log.exception("Unhandled error (%s): %r", upd_type, exception)

    # отвечаем на callback, чтобы телеграм не крутил колёсико бесконечно
    try:
        cb = event.update.callback_query
        if cb:
            await cb.answer("Произошла ошибка. Попробуйте ещё раз.", show_alert=False)
    except Exception:
        pass

# ---------- УТИЛИТЫ ----------
def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пинг", callback_data="ping")]
    ])

# ---------- ХЕНДЛЕРЫ ----------
@dp.message(CommandStart())
async def on_start(m: Message):
    await m.answer(
        "Я жив! Нажми кнопку, чтобы проверить цикл вебхука.",
        reply_markup=kb_main()
    )

@dp.callback_query(F.data == "ping")
async def on_ping(cb: CallbackQuery):
    await cb.message.edit_text("Понг ✅")
    await cb.answer()

# ---------- FASTAPI: healthz ----------
@app.get("/healthz")
async def healthz():
    return {"ok": True}

# ---------- FASTAPI: вебхук ----------
@app.post("/webhooks/telegram")
async def telegram_webhook(req: Request) -> Response:
    try:
        data = await req.json()
    except Exception:
        return Response(status_code=400)
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return Response(status_code=200)

# ---------- запуск локально (не используется на Render) ----------
# если вдруг нужно проверить локально: uvicorn main:app --reload
