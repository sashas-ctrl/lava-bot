import os
import re
import logging
from typing import Dict, List, Callable

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile, Update
)

# --- Логирование ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("tubecomy")

# --- ENV ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL", "")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "sashablogerr")

TARIFF_PRICE = int(os.getenv("TARIFF_PRICE", "1499"))
TARIFF_DAYS = int(os.getenv("TARIFF_DAYS", "30"))
PAY_CARD_URL = os.getenv("PAY_CARD_URL", "https://yookassa.ru/")

WHAT_INSIDE_URL = os.getenv("WHAT_INSIDE_URL", "")

# Фото (file_id из Telegram)
IMAGES = {
    "main": os.getenv("IMAGE_MAIN"),
    "email": os.getenv("IMAGE_EMAIL"),
    "join": os.getenv("IMAGE_JOIN"),
    "pay_card": os.getenv("IMAGE_PAY_CARD"),
    "pay_crypto": os.getenv("IMAGE_PAY_CRYPTO"),
    "inside": os.getenv("IMAGE_INSIDE"),
}

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required")

# --- Bot/Dispatcher/FastAPI ---
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
app = FastAPI()
# --- E-MAIL: SQLite (чтобы не спрашивать повторно никогда) ---
import sqlite3
from datetime import datetime

DB_PATH = "emails.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS emails (
                user_id INTEGER PRIMARY KEY,
                email TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

def get_email_db(user_id: int) -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT email FROM emails WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return row[0] if row else None

def save_email_db(user_id: int, email: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO emails (user_id, email, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              email=excluded.email,
              updated_at=excluded.updated_at
            """,
            (user_id, email, datetime.utcnow().isoformat())
        )

init_db()

# --- Память ---
screen_stack: Dict[int, List[str]] = {}
current_msgs: Dict[int, List[int]] = {}

# --- Утилиты ---
async def clear_msgs(chat_id: int):
    ids = current_msgs.get(chat_id, [])
    for mid in ids:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass
    current_msgs[chat_id] = []

def push_screen(uid: int, scr: str):
    screen_stack.setdefault(uid, []).append(scr)

def pop_screen(uid: int):
    if screen_stack.get(uid):
        screen_stack[uid].pop()

def peek_screen(uid: int) -> str | None:
    return screen_stack.get(uid, [])[-1] if screen_stack.get(uid) else None

async def send_block(chat_id: int, text: str, kb: InlineKeyboardMarkup, img_key: str):
    msg_ids = []
    if IMAGES.get(img_key):
        try:
            photo = IMAGES[img_key]
            m = await bot.send_photo(chat_id, photo=photo, caption=text, reply_markup=kb)
            msg_ids.append(m.message_id)
        except Exception:
            m = await bot.send_message(chat_id, text, reply_markup=kb)
            msg_ids.append(m.message_id)
    else:
        m = await bot.send_message(chat_id, text, reply_markup=kb)
        msg_ids.append(m.message_id)
    current_msgs.setdefault(chat_id, []).extend(msg_ids)

# --- Кнопки ---
def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"ВСТУПИТЬ — {TARIFF_PRICE}₽/{TARIFF_DAYS}дн", callback_data="join")],
        [
            InlineKeyboardButton(text="Что внутри?", callback_data="inside"),
            InlineKeyboardButton(text="Задать вопрос", url=f"https://t.me/{SUPPORT_USERNAME}")
        ]
    ])

def kb_join():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплата картой РФ", callback_data="pay_card")],
        [InlineKeyboardButton(text="🪙 Оплата криптой", callback_data="pay_crypto")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
    ])

def kb_pay_card():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"1 месяц — {TARIFF_PRICE}₽", url=PAY_CARD_URL)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
    ])

def kb_pay_crypto():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Связаться", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton(text="Оплатить картой РФ", callback_data="pay_card")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
    ])

def kb_inside():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ВСТУПИТЬ", callback_data="join")],
        [InlineKeyboardButton(text="Доп. вопросы", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
    ])

def kb_email():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
    ])

# --- Экраны ---
async def render_main(chat_id: int):
    await clear_msgs(chat_id)
    text = "<b>TubeComy</b>\n\nЗакрытое сообщество для тех, кто хочет монетизировать контент на YouTube.\nПоддержка, опыт и схемы заработка."
    await send_block(chat_id, text, kb_main(), "main")

async def render_email(chat_id: int):
    await clear_msgs(chat_id)
    text = "✉️ Введите ваш e-mail (например, ivan@example.com). Мы сохраним его один раз для связи и чеков."
    await send_block(chat_id, text, kb_email(), "email")

async def render_join(chat_id: int):
    await clear_msgs(chat_id)
    text = "Выберите способ оплаты:"
    await send_block(chat_id, text, kb_join(), "join")

async def render_pay_card(chat_id: int):
    await clear_msgs(chat_id)
    text = f"Доступ: <b>1 месяц</b> — {TARIFF_PRICE}₽\n\nПосле оплаты доступ активируется автоматически."
    await send_block(chat_id, text, kb_pay_card(), "pay_card")

async def render_pay_crypto(chat_id: int):
    await clear_msgs(chat_id)
    text = "🪙 Оплата криптой.\nНапишите нам — подскажем шаги.\nИли выберите другой способ."
    await send_block(chat_id, text, kb_pay_crypto(), "pay_crypto")

async def render_inside(chat_id: int):
    await clear_msgs(chat_id)
    # Пересылаем пост
    if WHAT_INSIDE_URL:
        await bot.send_message(chat_id, WHAT_INSIDE_URL)
    text = "А вот и детали нашего сообщества 👇"
    await send_block(chat_id, text, kb_inside(), "inside")

renderers: Dict[str, Callable[[int], None]] = {
    "main": render_main,
    "email": render_email,
    "join": render_join,
    "pay_card": render_pay_card,
    "pay_crypto": render_pay_crypto,
    "inside": render_inside,
}

async def show_screen(uid: int, screen: str):
    push_screen(uid, screen)
    fn = renderers.get(screen)
    if fn:
        await fn(uid)

# --- Handlers ---
@dp.message(F.text == "/start")
async def cmd_start(m: Message):
    screen_stack[m.from_user.id] = []
    current_msgs[m.chat.id] = []
    await show_screen(m.chat.id, "main")
    
@dp.callback_query(F.data == "join")
async def cb_join(cb: CallbackQuery):
    # читаем e-mail из БД (а не из user_emails)
    email = get_email_db(cb.from_user.id)
    if email:
        await show_screen(cb.from_user.id, "join")   # сразу выбор способа оплаты
    else:
        await show_screen(cb.from_user.id, "email")  # сначала спросим e-mail (один раз)
    await cb.answer()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", re.I)

@dp.message()
async def on_text(m: Message):
    # обрабатываем ввод e-mail только когда активен экран "email"
    if peek_screen(m.from_user.id) == "email":
        email = (m.text or "").strip()

        if not EMAIL_RE.match(email):
            await bot.send_message(m.chat.id, "❌ Некорректный e-mail. Попробуйте ещё раз.")
            return

        # сохраняем в БД (навсегда)
        save_email_db(m.from_user.id, email)
        await bot.send_message(m.chat.id, "✅ E-mail сохранён.")

        # убираем из стека экран "email", чтобы «Назад» потом не вел к нему
        pop_screen(m.from_user.id)

        # и сразу переходим к выбору оплаты
        await show_screen(m.chat.id, "join")
        
@dp.callback_query(F.data == "pay_card")
async def cb_card(cb: CallbackQuery):
    await show_screen(cb.from_user.id, "pay_card")
    await cb.answer()

@dp.callback_query(F.data == "pay_crypto")
async def cb_crypto(cb: CallbackQuery):
    await show_screen(cb.from_user.id, "pay_crypto")
    await cb.answer()

@dp.callback_query(F.data == "inside")
async def cb_inside(cb: CallbackQuery):
    await show_screen(cb.from_user.id, "inside")
    await cb.answer()

@dp.callback_query(F.data == "back")
async def cb_back(cb: CallbackQuery):
    uid = cb.from_user.id

    # снимаем текущий экран
    pop_screen(uid)

    # если следующий в стеке "email" — пропускаем его
    if peek_screen(uid) == "email":
        pop_screen(uid)

    prev = peek_screen(uid) or "main"
    await show_screen(uid, prev)
    await cb.answer()

# --- FastAPI webhook ---
@app.post("/webhooks/telegram")
async def tg_webhook(req: Request):
    data = await req.json()
    update = Update.model_validate(data)
    await dp.feed_webhook_update(bot, update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"ok": True}
