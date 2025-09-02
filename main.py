import os
import re
import csv
import sqlite3
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
)

# ---------- Логирование ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("tubecomy-bot")

# ---------- Конфиг ----------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

PRICE_RUB = int(os.getenv("PRICE_RUB", "1499"))
PERIOD_DAYS = int(os.getenv("PERIOD_DAYS", "30"))
PAYMENT_URL = os.getenv("PAYMENT_URL", "https://tubecomy.com/pay")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "sashablogerr")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DATA_DIR = Path(__file__).parent
DB_PATH = DATA_DIR / "contacts.db"

# ---------- БД ----------
def db_init():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_user_id INTEGER NOT NULL,
            tg_username TEXT,
            email TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(tg_user_id)")
    con.commit()
    con.close()

def save_email(tg_user_id: int, tg_username: str | None, email: str):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO contacts (tg_user_id, tg_username, email, created_at) VALUES (?, ?, ?, ?)",
        (tg_user_id, tg_username, email, datetime.utcnow().isoformat())
    )
    con.commit()
    con.close()

def export_csv(path: Path):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT tg_user_id, tg_username, email, created_at FROM contacts ORDER BY id DESC")
    rows = cur.fetchall()
    con.close()

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["tg_user_id", "tg_username", "email", "created_at_utc"])
        writer.writerows(rows)

# ---------- Валидация email ----------
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

def is_valid_email(s: str) -> bool:
    return bool(EMAIL_RE.match(s.strip()))

# ---------- Бот ----------
bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

class JoinFlow(StatesGroup):
    waiting_email = State()

def main_menu() -> InlineKeyboardMarkup:
    btn_join = InlineKeyboardButton(text=f"ВСТУПИТЬ — {PRICE_RUB} ₽ / {PERIOD_DAYS} дней", callback_data="join")
    btn_inside = InlineKeyboardButton(text="Что внутри?", callback_data="what_inside")
    btn_support = InlineKeyboardButton(text="Задать вопрос", url=f"https://t.me/{SUPPORT_USERNAME}")
    return InlineKeyboardMarkup(inline_keyboard=[[btn_join],[btn_inside, btn_support]])

WELCOME_TEXT = (
    "<b>TubeComy</b>\n"
    "Платформа для развития и заработка на YouTube\n\n"
    "🔒 Закрытое сообщество: материалы, разборы и поддержка команды.\n"
    f"💳 Подписка: {PRICE_RUB} ₽ / {PERIOD_DAYS} дней\n\n"
    "Выберите действие 👇"
)

@dp.message(CommandStart())
async def on_start(m: Message):
    await m.answer(WELCOME_TEXT, reply_markup=main_menu())

@dp.callback_query(F.data == "what_inside")
async def on_inside(cb: CallbackQuery):
    try:
        if INSIDE_POST_ID <= 0:
            await cb.message.answer(
                "Пост пока не привязан. Напишите в поддержку.",
                reply_markup=main_menu()
            )
            await cb.answer()
            return

        if INSIDE_CHANNEL:
            # публичный канал: копируем пост по @username
            await bot.copy_message(
                chat_id=cb.message.chat.id,
                from_chat_id=INSIDE_CHANNEL,
                message_id=INSIDE_POST_ID
            )
        elif INSIDE_CHANNEL_ID:
            # вариант для приватного канала по числовому id (на будущее)
            await bot.copy_message(
                chat_id=cb.message.chat.id,
                from_chat_id=int(INSIDE_CHANNEL_ID),
                message_id=INSIDE_POST_ID
            )
        else:
            await cb.message.answer(
                "Не задан источник поста. Напишите в поддержку.",
                reply_markup=main_menu()
            )
            await cb.answer()
            return

        # вернем клавиатуру отдельным сообщением
        await cb.message.answer("Ещё вопросы? Выберите действие👇", reply_markup=main_menu())

    except Exception as e:
        # если пост удалён/ID неверный/бота нет в канале — покажем заглушку
        await cb.message.answer(
            "Не удалось показать пост (возможно, неверный ID или нет доступа). "
            "Напишите в поддержку — пришлём пример.",
            reply_markup=main_menu()
        )
    finally:
        await cb.answer()

@dp.callback_query(F.data == "join")
async def on_join(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer(
        "📧 Введите ваш <b>e-mail</b>.\n"
        "Он нужен для отправки чека и восстановления доступа."
    )
    await state.set_state(JoinFlow.waiting_email)
    await cb.answer()

@dp.message(JoinFlow.waiting_email)
async def on_email(m: Message, state: FSMContext):
    email = m.text.strip()
    if not is_valid_email(email):
        await m.answer("Похоже, это не e-mail. Отправьте, пожалуйста, e-mail в формате <code>name@example.com</code>.")
        return

    # сохраняем автоматически
    save_email(m.from_user.id, m.from_user.username or "", email)
    await state.clear()
    log.info(f"Saved email for {m.from_user.id} (@{m.from_user.username}): {email}")

    # кнопка оплаты (можно подставить email в параметр)
    pay_url = f"{PAYMENT_URL}?customer_email={email}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Оплатить {PRICE_RUB} ₽", url=pay_url)]
    ])
    await m.answer(
        f"Спасибо! ✅\n\n"
        f"Подписка: <b>{PRICE_RUB} ₽</b> / {PERIOD_DAYS} дней\n"
        "Нажмите кнопку ниже, чтобы перейти к оплате:",
        reply_markup=kb
    )

@dp.message()
async def fallback(m: Message):
    await m.answer("Выберите действие ниже 👇", reply_markup=main_menu())

# --- Админ: выгрузка CSV
@dp.message(Command("export"))
async def cmd_export(m: Message):
    if m.from_user.id != ADMIN_ID or ADMIN_ID == 0:
        return
    tmp = DATA_DIR / "emails_export.csv"
    export_csv(tmp)
    await m.answer_document(FSInputFile(tmp), caption="Экспорт контактов (CSV).")
    try:
        tmp.unlink()
    except Exception:
        pass

# ---------- FastAPI для Render ----------
app = FastAPI(title="TubeComy Bot")
_polling_task: asyncio.Task | None = None

@app.get("/healthz")
async def health():
    return {"status": "ok"}

@app.on_event("startup")
async def _startup():
    db_init()
    # на всякий случай выключаем вебхук (чтобы polling работал)
    await bot.delete_webhook(drop_pending_updates=True)

    async def _poll():
        await dp.start_polling(bot)

    global _polling_task
    _polling_task = asyncio.create_task(_poll())

@app.on_event("shutdown")
async def _shutdown():
    global _polling_task
    if _polling_task:
        _polling_task.cancel()
    await bot.session.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
