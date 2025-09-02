import os
import re
import sqlite3
import logging
from datetime import datetime
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)

# =====================  ENV & LOGS  =====================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL")  # например: https://your-app.onrender.com
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "sashablogerr")

TARIFF_PRICE = int(os.getenv("TARIFF_PRICE", "1499"))
TARIFF_DAYS = int(os.getenv("TARIFF_DAYS", "30"))

# Ссылка для оплаты картой (ЮKassa):
PAY_CARD_URL = os.getenv("PAY_CARD_URL", "https://yookassa.ru/some/your/link")

# Ссылка на пост «Что внутри?» — например https://t.me/greycomunity/5
WHAT_INSIDE_URL = os.getenv("WHAT_INSIDE_URL", "https://t.me/greycomunity/5")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("tubecomy-bot")

# =====================  BOT/DP/APP  =====================

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
app = FastAPI()

# =====================  DB (email)  =====================

DB_PATH = "emails.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS emails (
                user_id INTEGER PRIMARY KEY,
                email   TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

def get_email(user_id: int) -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT email FROM emails WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return row[0] if row else None

def save_email(user_id: int, email: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO emails (user_id, email, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET email=excluded.email, created_at=excluded.created_at
            """,
            (user_id, email, datetime.utcnow().isoformat()),
        )

init_db()

# =====================  STATE (экраны/стек)  =====================

# стеки экранов и последние сообщения на пользователя
screen_stack: dict[int, list[str]] = {}
current_msgs: dict[int, list[int]] = {}

def push_screen(user_id: int, screen: str):
    screen_stack.setdefault(user_id, [])
    screen_stack[user_id].append(screen)

def pop_screen(user_id: int) -> str | None:
    if user_id in screen_stack and screen_stack[user_id]:
        return screen_stack[user_id].pop()
    return None

def peek_screen(user_id: int) -> str | None:
    if user_id in screen_stack and screen_stack[user_id]:
        return screen_stack[user_id][-1]
    return None

def reset_stack(user_id: int):
    screen_stack[user_id] = []

async def clean_messages(chat_id: int):
    # удаляем предыдущие бот-сообщения этого экрана
    ids = current_msgs.get(chat_id, [])
    for mid in ids:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass
    current_msgs[chat_id] = []

async def send_block(chat_id: int, text: str, kb: InlineKeyboardMarkup | None = None):
    msg = await bot.send_message(chat_id, text, reply_markup=kb)
    current_msgs.setdefault(chat_id, [])
    current_msgs[chat_id].append(msg.message_id)

# =====================  КНОПКИ  =====================

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"ВСТУПИТЬ — {TARIFF_PRICE} ₽ / {TARIFF_DAYS} дней", callback_data="join")],
            [
                InlineKeyboardButton(text="Что внутри?", callback_data="inside"),
                InlineKeyboardButton(text="Задать вопрос", url=f"https://t.me/{SUPPORT_USERNAME}")
            ],
        ]
    )

def kb_join() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оплата картой РФ", callback_data="pay_card")],
            [InlineKeyboardButton(text="Оплата криптой", callback_data="pay_crypto")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
        ]
    )

def kb_pay_card() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"1 месяц — {TARIFF_PRICE} ₽", url=PAY_CARD_URL)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
        ]
    )

def kb_pay_crypto() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Связаться", url=f"https://t.me/{SUPPORT_USERNAME}")],
            [InlineKeyboardButton(text="Оплатить картой РФ", callback_data="pay_card")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
        ]
    )

def kb_inside() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"ВСТУПИТЬ — {TARIFF_PRICE} ₽ / {TARIFF_DAYS} дней", callback_data="join")],
            [
                InlineKeyboardButton(text="Задать доп. вопросы", url=f"https://t.me/{SUPPORT_USERNAME}"),
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back"),
            ],
        ]
    )

def kb_email() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="back")]
        ]
    )

# =====================  РЕНДЕРЫ ЭКРАНОВ  =====================

async def render_main(chat_id: int):
    await clean_messages(chat_id)
    text = (
        "<b>TubeComy</b>\n"
        "Закрытое сообщество, которое помогает монетизировать контент на YouTube и поддерживает во всех начинаниях.\n"
        "Внутри — методики, практические разборы и поддержка команды для вашего роста.\n\n"
        "Выберите действие 👇"
    )
    await send_block(chat_id, text, kb_main())
    push_screen(chat_id, "main")

async def render_join(chat_id: int):
    await clean_messages(chat_id)
    text = (
        "<b>Выберите способ оплаты:</b>\n\n"
        "• <b>Оплата картой РФ</b> — быстро и удобно через ЮKassa\n"
        "• <b>Оплата криптой</b> — напишите нам, мы поможем\n"
    )
    await send_block(chat_id, text, kb_join())
    push_screen(chat_id, "join")

async def render_pay_card(chat_id: int):
    await clean_messages(chat_id)
    text = (
        "<b>Тарифы</b>\n\n"
        f"• <b>1 месяц</b> — <b>{TARIFF_PRICE} ₽</b>\n\n"
        "После оплаты доступ будет выдан автоматически в течение нескольких минут."
    )
    await send_block(chat_id, text, kb_pay_card())
    push_screen(chat_id, "pay_card")

async def render_pay_crypto(chat_id: int):
    await clean_messages(chat_id)
    text = (
        "<b>Оплата криптовалютой</b>\n\n"
        "Напишите нам — подскажем удобный способ и сумму к оплате.\n"
        "Либо вернитесь и выберите оплату картой РФ."
    )
    await send_block(chat_id, text, kb_pay_crypto())
    push_screen(chat_id, "pay_crypto")

def parse_telegram_post_link(link: str) -> tuple[str, int] | None:
    """
    Превращает https://t.me/username/123 -> ('@username', 123)
    """
    try:
        u = urlparse(link)
        if u.netloc not in ("t.me", "telegram.me"):
            return None
        parts = u.path.strip("/").split("/")
        if len(parts) != 2:
            return None
        username, mid = parts
        msg_id = int(mid)
        return f"@{username}", msg_id
    except Exception:
        return None

async def render_inside(chat_id: int):
    await clean_messages(chat_id)

    # попытка скопировать пост из канала
    ok = False
    parsed = parse_telegram_post_link(WHAT_INSIDE_URL)
    if parsed:
        from_chat, msg_id = parsed
        try:
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=from_chat,
                message_id=msg_id,
                reply_markup=kb_inside(),
            )
            # запоминаем это сообщение
            current_msgs.setdefault(chat_id, []).append(
                current_msgs[chat_id][-1] + 1 if current_msgs[chat_id] else 0
            )
            ok = True
        except Exception as e:
            log.warning("copy_message failed: %s", e)

    if not ok:
        # запасной текст, если пост не получилось скопировать
        text = (
            "<b>Что внутри TubeComy?</b>\n\n"
            "• Практические материалы по росту YouTube-каналов\n"
            "• Контент-стратегии, упаковка и продакшн\n"
            "• Методики монетизации и схемы заработка\n"
            "• Разборы и поддержка от команды\n\n"
            f"Подписка: <b>{TARIFF_PRICE} ₽</b> / <b>{TARIFF_DAYS}</b> дней"
        )
        await send_block(chat_id, text, kb_inside())

    push_screen(chat_id, "inside")

EMAIL_PROMPT = (
    "<b>Введите ваш e-mail</b> одним сообщением.\n\n"
    "Мы используем его для отправки квитанций и техподдержки.\n\n"
    "Пример: <code>name@gmail.com</code>"
)

async def render_email(chat_id: int):
    await clean_messages(chat_id)
    await send_block(chat_id, EMAIL_PROMPT, kb_email())
    push_screen(chat_id, "email")

# =====================  ХЕНДЛЕРЫ  =====================

@dp.message(CommandStart())
async def on_start(m: Message):
    reset_stack(m.from_user.id)
    current_msgs[m.chat.id] = []
    await render_main(m.chat.id)

@dp.callback_query(F.data == "join")
async def cb_join(cb: CallbackQuery):
    # если e-mail не сохранён — просим сначала e-mail
    email = get_email(cb.from_user.id)
    if email:
        await render_join(cb.from_user.id)
    else:
        await render_email(cb.from_user.id)
    await cb.answer()

@dp.callback_query(F.data == "pay_card")
async def cb_pay_card(cb: CallbackQuery):
    await render_pay_card(cb.from_user.id)
    await cb.answer()

@dp.callback_query(F.data == "pay_crypto")
async def cb_pay_crypto(cb: CallbackQuery):
    await render_pay_crypto(cb.from_user.id)
    await cb.answer()

@dp.callback_query(F.data == "inside")
async def cb_inside(cb: CallbackQuery):
    await render_inside(cb.from_user.id)
    await cb.answer()

@dp.callback_query(F.data == "back")
async def cb_back(cb: CallbackQuery):
    # снимаем текущий экран
    pop_screen(cb.from_user.id)
    prev = peek_screen(cb.from_user.id)
    # если пусто — возвращаем на главный
    if not prev:
        await render_main(cb.from_user.id)
        await cb.answer()
        return

    # перерисовываем предыдущий экран
    if prev == "main":
        await render_main(cb.from_user.id)
    elif prev == "join":
        await render_join(cb.from_user.id)
    elif prev == "pay_card":
        await render_pay_card(cb.from_user.id)
    elif prev == "pay_crypto":
        await render_pay_crypto(cb.from_user.id)
    elif prev == "inside":
        await render_inside(cb.from_user.id)
    elif prev == "email":
        await render_email(cb.from_user.id)
    else:
        await render_main(cb.from_user.id)
    await cb.answer()

# Приём e-mail
EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)

@dp.message(F.text)
async def on_text(m: Message):
    # при активном экране email — принимаем e-mail
    if peek_screen(m.from_user.id) == "email":
        text = (m.text or "").strip()
        if EMAIL_RE.match(text):
            save_email(m.from_user.id, text)
            await bot.send_message(m.chat.id, "✅ E-mail сохранён.")
            # после сохранения — сразу к выбору оплаты
            pop_screen(m.from_user.id)  # закрываем экран email
            await render_join(m.from_user.id)
        else:
            await bot.send_message(m.chat.id, "✍️ Введите корректный e-mail или нажмите «Отмена».")
        return

# =====================  WEBHOOK (Render)  =====================

@app.post("/webhooks/telegram")
async def telegram_webhook(req: Request):
    body = await req.body()
    await dp.feed_webhook_update(bot, body.decode())
    return {"ok": True}

@app.get("/")
async def index():
    return {"ok": True}

# для локального запуска (если потребуется)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
