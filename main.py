import os
import re
import sqlite3
import logging
from pathlib import Path
from typing import Dict, List, Callable, Awaitable

from fastapi import FastAPI, Request
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    Update, Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)

# ----------------------------- ЛОГИ ---------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)
log = logging.getLogger("tubecomy-bot")

# ----------------------------- ENV ----------------------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
INSIDE_CHANNEL = os.getenv("INSIDE_CHANNEL", "")        # @greycomunity
INSIDE_POST_ID = int(os.getenv("INSIDE_POST_ID", "0"))  # 5
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "sashablogerr")

TARIFF_PRICE = int(os.getenv("TARIFF_PRICE", "1499"))
TARIFF_DAYS = int(os.getenv("TARIFF_DAYS", "30"))
YOOKASSA_URL = os.getenv("YOOKASSA_URL", "https://pay.yookassa.ru/")
GRACE_HOURS = int(os.getenv("GRACE_HOURS", "24"))

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ----------------------------- БД (email) ---------------------------
DATA_DIR = Path(__file__).parent
DB_PATH = DATA_DIR / "emails.db"
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_email_cache: Dict[int, str] = {}  # user_id -> email

def db_init():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            email TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()

def get_email(user_id: int) -> str | None:
    if user_id in _email_cache:
        return _email_cache[user_id]
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT email FROM emails WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    con.close()
    if row:
        _email_cache[user_id] = row[0]
        return row[0]
    return None

def save_email(user_id: int, username: str | None, email: str):
    _email_cache[user_id] = email
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO emails (user_id, username, email, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(user_id) DO UPDATE SET
          username=excluded.username,
          email=excluded.email,
          updated_at=datetime('now')
    """, (user_id, username or "", email))
    con.commit()
    con.close()

# ----------------------------- НАВИГАЦИЯ ЭКРАНОВ --------------------
# Стек имён экранов и список message_id текущего экрана — чтобы «Назад» работал как надо
screen_stack: Dict[int, List[str]] = {}          # user_id -> ["main", "join", ...]
current_msgs: Dict[int, List[int]] = {}          # user_id -> [msg_id, ...]

# Рендер-функции по имени экрана (без удаления прошлого — этим занимается навигатор)
Renderer = Callable[[int], Awaitable[List[int]]]
renderers: Dict[str, Renderer] = {}

async def clear_current(user_id: int):
    """Удаляем ВСЕ сообщения текущего экрана (только то, что бот прислал для этого экрана)."""
    for mid in current_msgs.get(user_id, []):
        try:
            await bot.delete_message(user_id, mid)
        except Exception:
            pass
    current_msgs[user_id] = []

async def show_screen(user_id: int, name: str):
    """Переключение на экран: удаляем текущий, рендерим новый, пушим имя в стек."""
    await clear_current(user_id)
    if name not in renderers:
        raise RuntimeError(f"Unknown screen: {name}")
    msg_ids = await renderers[name](user_id)
    current_msgs[user_id] = msg_ids
    screen_stack.setdefault(user_id, []).append(name)

async def back_screen(user_id: int, fallback_name: str = "main"):
    """Назад: удаляем текущий, убираем имя из стека и рендерим предыдущий."""
    await clear_current(user_id)
    stack = screen_stack.setdefault(user_id, [])
    if stack:
        stack.pop()  # убрать текущее имя
    prev = stack[-1] if stack else fallback_name
    msg_ids = await renderers[prev](user_id)
    current_msgs[user_id] = msg_ids
    if not stack or stack[-1] != prev:
        stack.append(prev)

# ----------------------------- КЛАВИАТУРЫ ---------------------------
def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"ВСТУПИТЬ — {TARIFF_PRICE} ₽ / {TARIFF_DAYS} дней", callback_data="join")],
        [
            InlineKeyboardButton(text="Что внутри?", callback_data="inside"),
            InlineKeyboardButton(text="Задать вопрос", url=f"https://t.me/{SUPPORT_USERNAME}")
        ],
    ])

def kb_join() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплата картой РФ", callback_data="pay_card")],
        [InlineKeyboardButton(text="🪙 Оплата криптой", callback_data="pay_crypto")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
    ])

def kb_pay_card(email: str) -> InlineKeyboardMarkup:
    pay_url = f"{YOOKASSA_URL}?customer_email={email}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Оплатить {TARIFF_PRICE} ₽ / {TARIFF_DAYS} дней", url=pay_url)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_join")],
    ])

def kb_pay_crypto() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Связаться", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton(text="💳 Оплатить картой РФ", callback_data="pay_card")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_join")],
    ])

def kb_inside_footer() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"ВСТУПИТЬ — {TARIFF_PRICE} ₽ / {TARIFF_DAYS} дней", callback_data="join")],
        [
            InlineKeyboardButton(text="Задать доп.вопросы", url=f"https://t.me/{SUPPORT_USERNAME}"),
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back"),
        ]
    ])

def kb_email_prompt() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
    ])

# ----------------------------- ТЕКСТЫ -------------------------------
WELCOME_TEXT = (
    "<b>TubeComy</b>\n\n"
    "Закрытое сообщество, которое помогает монетизировать любой контент на YouTube "
    "и поддерживает во всех начинаниях.\n\n"
    "Здесь вы найдёте массу структурированной информации, практики и поддержку "
    "в вопросах заработка на YouTube.\n\n"
    "Выберите действие 👇"
)

JOIN_TEXT = (
    "<b>Выберите способ оплаты</b>\n\n"
    "💳 Оплата картой РФ — быстрый и удобный способ через ЮKassa.\n"
    "🪙 Оплата криптой — если удобнее, напишите нам, подскажем формат.\n"
)

PAY_CARD_TEXT = (
    "<b>Тарифы</b>\n\n"
    f"• 1 месяц — {TARIFF_PRICE} ₽\n"
)

PAY_CRYPTO_TEXT = (
    "<b>Оплата криптовалютой</b>\n\n"
    "Напишите нам в личные сообщения, подскажем актуальный способ и адрес.\n"
    "Либо вернитесь и оплатите картой РФ.\n"
)

EMAIL_PROMPT_TEXT = (
    "📧 Пожалуйста, укажите ваш <b>e-mail</b> для отправки чека и восстановления доступа.\n\n"
    "Отправьте e-mail одним сообщением (формат: <code>name@example.com</code>)."
)

EMAIL_SAVED_TEXT = "✅ Спасибо! E-mail сохранён. Переходим к выбору способа оплаты."

# ----------------------------- РЕНДЕР ЭКРАНОВ -----------------------
async def render_main(chat_id: int) -> List[int]:
    m = await bot.send_message(chat_id, WELCOME_TEXT, reply_markup=kb_main())
    return [m.message_id]

async def render_email(chat_id: int) -> List[int]:
    m = await bot.send_message(chat_id, EMAIL_PROMPT_TEXT, reply_markup=kb_email_prompt())
    return [m.message_id]

async def render_join(chat_id: int) -> List[int]:
    m = await bot.send_message(chat_id, JOIN_TEXT, reply_markup=kb_join())
    return [m.message_id]

async def render_pay_card(chat_id: int) -> List[int]:
    email = get_email(chat_id) or "unknown@example.com"
    m = await bot.send_message(chat_id, PAY_CARD_TEXT, reply_markup=kb_pay_card(email))
    return [m.message_id]

async def render_pay_crypto(chat_id: int) -> List[int]:
    m = await bot.send_message(chat_id, PAY_CRYPTO_TEXT, reply_markup=kb_pay_crypto())
    return [m.message_id]

async def render_inside(chat_id: int) -> List[int]:
    ids: List[int] = []
    # копируем пост из канала (бот может удалить своё скопированное сообщение)
    if INSIDE_CHANNEL and INSIDE_POST_ID > 0:
        try:
            res = await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=INSIDE_CHANNEL,
                message_id=INSIDE_POST_ID
            )
            # aiogram v3: copy_message возвращает объект с message_id
            copy_id = getattr(res, "message_id", None)
            if copy_id:
                ids.append(copy_id)
        except Exception as e:
            log.warning(f"copy_message failed: {e}")
            fallback = (
                "<b>Что внутри TubeComy?</b>\n\n"
                "✔️ Материалы по росту каналов\n"
                "✔️ Разборы и шаблоны\n"
                "✔️ Поддержка команды\n"
                f"Подписка: {TARIFF_PRICE} ₽ / {TARIFF_DAYS} дней"
            )
            m1 = await bot.send_message(chat_id, fallback)
            ids.append(m1.message_id)
    footer = await bot.send_message(chat_id, "Выберите действие 👇", reply_markup=kb_inside_footer())
    ids.append(footer.message_id)
    return ids

# зарегистрируем рендеры
renderers.update({
    "main": render_main,
    "email": render_email,
    "join": render_join,
    "pay_card": render_pay_card,
    "pay_crypto": render_pay_crypto,
    "inside": render_inside,
})

# ----------------------------- ХЕНДЛЕРЫ -----------------------------
@dp.message(F.text == "/start")
async def cmd_start(m: Message):
    screen_stack[m.from_user.id] = []
    current_msgs[m.from_user.id] = []
    await show_screen(m.chat.id, "main")

@dp.callback_query(F.data == "join")
async def cb_join(cb: CallbackQuery):
    # ТЕПЕРЬ: при нажатии «ВСТУПИТЬ» сначала проверяем e-mail.
    email = get_email(cb.from_user.id)
    if email:
        await show_screen(cb.from_user.id, "join")      # уже знаем e-mail → сразу выбор способа оплаты
    else:
        await show_screen(cb.from_user.id, "email")     # сначала просим e-mail (один раз)
    await cb.answer()

@dp.callback_query(F.data == "pay_card")
async def cb_pay_card(cb: CallbackQuery):
    await show_screen(cb.from_user.id, "pay_card")
    await cb.answer()

@dp.callback_query(F.data == "pay_crypto")
async def cb_pay_crypto(cb: CallbackQuery):
    await show_screen(cb.from_user.id, "pay_crypto")
    await cb.answer()

@dp.callback_query(F.data == "inside")
async def cb_inside(cb: CallbackQuery):
    await show_screen(cb.from_user.id, "inside")
    await cb.answer()

@dp.callback_query(F.data == "back")
async def cb_back(cb: CallbackQuery):
    await back_screen(cb.from_user.id, fallback_name="main")
    await cb.answer()

@dp.callback_query(F.data == "back_join")
async def cb_back_join(cb: CallbackQuery):
    # из оплаты вернуться к экрану выбора способов оплаты
    await show_screen(cb.from_user.id, "join")
    await cb.answer()

# Приходит e-mail сообщением (работает на экране "email")
@dp.message(F.text.func(lambda t: bool(t) and EMAIL_RE.match(t.strip() or "")))
async def on_email_message(m: Message):
    # Если e-mail уже сохранён — не просим снова (и переключаем на выбор способов оплаты)
    if get_email(m.from_user.id):
        await show_screen(m.from_user.id, "join")
        return

    email = m.text.strip()
    save_email(m.from_user.id, m.from_user.username, email)
    await m.answer("✅ E-mail сохранён.")
    await show_screen(m.chat.id, "join")

@dp.message()
async def fallback(m: Message):
    # Любой другой текст → просто показать главное меню
    await show_screen(m.chat.id, "main")

# ----------------------------- FASTAPI & WEBHOOK --------------------
app = FastAPI()

@app.post("/webhooks/telegram")
async def telegram_webhook(req: Request):
    data = await req.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.get("/")
async def health():
    return {"ok": True}

@app.on_event("startup")
async def on_startup():
    db_init()
    if PUBLIC_URL:
        url = f"{PUBLIC_URL}/webhooks/telegram"
        await bot.set_webhook(url)
        log.info(f"Webhook set to {url}")
    else:
        log.warning("PUBLIC_URL not set — webhook won't be installed")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()
