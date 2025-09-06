import os
import re
import logging
from typing import Dict, List, Callable, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Update, Message, CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup
)

# ============ ЛОГИ ============
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("tubecomy-bot")

# ============ КОНФИГ ============
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "sashablogerr")
PRICE_RUB = int(os.getenv("PRICE_RUB", "1499"))
PERIOD_DAYS = int(os.getenv("PERIOD_DAYS", "30"))
CARD_PAY_URL = os.getenv("CARD_PAY_URL", "")  # если пусто — кнопка оплаты картой не показывается

if not BOT_TOKEN or not PUBLIC_URL:
    raise RuntimeError("ENV BOT_TOKEN и PUBLIC_URL обязательны")

# «Что внутри?» — статический текст, как просил
WHAT_INSIDE_TEXT = (
    "<b>ЧТО ВАС ЖДЁТ С НАМИ?</b>\n\n"
    "<b>Уже внутри:</b>\n"
    "🔍 Классная ниша с низкой конкуренцией — о ней мало кто знает прямо сейчас\n"
    "📖 Полный гайд — полный разбор ниши, пошаговая инструкция для старта работы, разбор конкурентов\n"
    "🚀 Методы буста видео — помогут отправить ваши видео в космос\n"
    "🧭 Методика поиска новых ниш — чтобы всегда знать, куда двигаться дальше\n"
    "📞 Общий созвон 2 раза в месяц — ответы на вопросы, разборы, инсайды каждый месяц, стабильно\n\n"
    "<b>Скоро появится:</b>\n"
    "🛡 Разборы блокировок каналов — и как их обходить\n"
    "🎯 Новая ниша — также с полным гайдом\n"
    "🎶 Работа с треками напрямую на себя — без посредников и с большей выгодой (+бонус)\n"
    "…"
)

# ============ BOT / DP / APP ============
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

# ============ ПАМЯТЬ ПОЛЬЗОВАТЕЛЕЙ ============
user_emails: Dict[int, str] = {}              # id -> email
current_msgs: Dict[int, List[int]] = {}        # id -> список id сообщений для удаления
screen_stack: Dict[int, List[str]] = {}        # id -> стек экранов (для «Назад»)

# ============ УТИЛИТЫ ============
def btn_url(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)

def btn_cb(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)

def t_me(username: str) -> str:
    return f"https://t.me/{username.lstrip('@')}"

async def clear_msgs(chat_id: int):
    """Удаляет ВСЕ текущие сообщения этого экрана (один блок)."""
    ids = current_msgs.get(chat_id, [])
    for mid in ids:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass
    current_msgs[chat_id] = []

async def send_block(chat_id: int, text: str, markup: Optional[InlineKeyboardMarkup] = None):
    """Отправляет ОДНО сообщение и запоминает его, чтобы корректно удалять при смене экрана."""
    await clear_msgs(chat_id)
    msg = await bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)
    current_msgs.setdefault(chat_id, []).append(msg.message_id)

def main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn_cb("ВСТУПИТЬ", "join")],
        [btn_cb("Что внутри?", "inside"), btn_url("Задать вопрос", t_me(SUPPORT_USERNAME))]
    ])

def join_kb() -> InlineKeyboardMarkup:
    row1 = [btn_cb("Оплата картой РФ", "pay_card")]
    if not CARD_PAY_URL:
        row1 = []  # скрываем кнопку, если нет ссылки
    kb = []
    if row1:
        kb.append(row1)
    kb.append([btn_cb("Оплата криптой", "pay_crypto")])
    kb.append([btn_cb("⬅️ Назад", "back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def inside_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn_cb("ВСТУПИТЬ", "join")],
        [btn_url("Задать доп.вопросы", t_me(SUPPORT_USERNAME)), btn_cb("⬅️ Назад", "back")]
    ])

def pay_card_kb() -> InlineKeyboardMarkup:
    rows = []
    if CARD_PAY_URL:
        rows.append([btn_url(f"Оплатить {PRICE_RUB} ₽ / {PERIOD_DAYS} дней", CARD_PAY_URL)])
    rows.append([btn_cb("⬅️ Назад", "back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def pay_crypto_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn_url("Связаться", t_me(SUPPORT_USERNAME))],
        [btn_cb("Оплатить картой РФ", "pay_card") if CARD_PAY_URL else btn_cb("—", "noop")],
        [btn_cb("⬅️ Назад", "back")]
    ])

def push_screen(chat_id: int, name: str):
    screen_stack.setdefault(chat_id, [])
    # не даём возвращаться на e-mail, если он уже сохранён
    if name == "email" and chat_id in user_emails:
        name = "join"
    screen_stack[chat_id].append(name)

def pop_screen(chat_id: int) -> str:
    """Возвращает имя предыдущего экрана. Пусто -> main. Пропускает email, если уже сохранён."""
    stack = screen_stack.setdefault(chat_id, [])
    if stack:
        stack.pop()
    while stack and stack[-1] == "email" and chat_id in user_emails:
        stack.pop()
    return stack[-1] if stack else "main"

async def show_screen(chat_id: int, name: str):
    """Роутер экранов."""
    renderers: Dict[str, Callable[[int], None]] = {
        "main": render_main,
        "join": render_join,
        "email": render_email,
        "inside": render_inside,
        "pay_card": render_pay_card,
        "pay_crypto": render_pay_crypto,
    }
    func = renderers.get(name, render_main)
    push_screen(chat_id, name)
    await func(chat_id)

# ============ РЕНДЕРЫ ============
async def render_main(chat_id: int):
    text = (
        "<b>TubeComy</b>\n\n"
        "Закрытое сообщество для тех, кто хочет монетизировать контент на YouTube.\n"
        "Поддержка, опыт и схемы заработка.\n\n"
        f"Подписка: <b>{PRICE_RUB} ₽</b> / <b>{PERIOD_DAYS} дней</b>\n\n"
        "Выберите действие 👇"
    )
    await send_block(chat_id, text, main_kb())

async def render_join(chat_id: int):
    text = (
        "Выберите способ оплаты:\n"
        "— Картой РФ (ЮKassa/эквайринг)\n"
        "— Криптовалютой (через поддержку)\n\n"
        "Можно вернуться назад к главному меню."
    )
    await send_block(chat_id, text, join_kb())

async def render_email(chat_id: int):
    # если email уже есть — сразу на выбор оплаты
    if chat_id in user_emails:
        await show_screen(chat_id, "join")
        return
    text = (
        "Пожалуйста, укажите ваш e-mail (один раз) — он нужен для связи по подписке.\n\n"
        "Пример: <code>name@example.com</code>\n\n"
        "Можно вернуться назад, если передумали."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[btn_cb("⬅️ Назад", "back")]])
    await send_block(chat_id, text, kb)

async def render_inside(chat_id: int):
    await send_block(chat_id, WHAT_INSIDE_TEXT, inside_kb())

async def render_pay_card(chat_id: int):
    if not CARD_PAY_URL:
        await send_block(chat_id, "Ссылка на оплату картой пока не настроена.", pay_card_kb())
        return
    text = f"Оплата картой РФ. Тариф: <b>{PRICE_RUB} ₽</b> / <b>{PERIOD_DAYS} дней</b>."
    await send_block(chat_id, text, pay_card_kb())

async def render_pay_crypto(chat_id: int):
    text = (
        "Оплата криптовалютой: напишите в поддержку, всё подскажем.\n"
        "Также можно вернуться и выбрать оплату картой РФ."
    )
    await send_block(chat_id, text, pay_crypto_kb())

# ============ ВАЛИДАЦИЯ EMAIL ============
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

# ============ ХЕНДЛЕРЫ ============
@dp.message(CommandStart())
async def on_start(m: Message):
    screen_stack[m.from_user.id] = []
    current_msgs[m.from_user.id] = []
    await show_screen(m.chat.id, "main")

@dp.callback_query(F.data == "join")
async def cb_join(cb: CallbackQuery):
    # если e-mail уже есть — сразу к выбору оплаты, иначе попросим e-mail
    if cb.from_user.id in user_emails:
        await show_screen(cb.from_user.id, "join")
    else:
        await show_screen(cb.from_user.id, "email")
    await cb.answer()

@dp.callback_query(F.data == "inside")
async def cb_inside(cb: CallbackQuery):
    await show_screen(cb.from_user.id, "inside")
    await cb.answer()

@dp.callback_query(F.data == "pay_card")
async def cb_pay_card(cb: CallbackQuery):
    await show_screen(cb.from_user.id, "pay_card")
    await cb.answer()

@dp.callback_query(F.data == "pay_crypto")
async def cb_pay_crypto(cb: CallbackQuery):
    await show_screen(cb.from_user.id, "pay_crypto")
    await cb.answer()

@dp.callback_query(F.data == "back")
async def cb_back(cb: CallbackQuery):
    prev_name = pop_screen(cb.from_user.id)
    await show_screen(cb.from_user.id, prev_name)
    await cb.answer()

# ловим e-mail только когда активен экран "email"
@dp.message()
async def on_text(m: Message):
    stack = screen_stack.get(m.from_user.id, [])
    if stack and stack[-1] == "email":
        email = (m.text or "").strip()
        if EMAIL_RE.match(email):
            user_emails[m.from_user.id] = email
            await m.answer("✅ E-mail сохранён.")
            # не держим пользователя на экране email — сразу к выбору оплаты
            await show_screen(m.chat.id, "join")
        else:
            await m.answer("Похоже, это не e-mail. Пример: name@example.com")

# ============ ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК ============
@dp.error()
async def on_error(event, exception):
    try:
        upd_type = event.update.event_type
    except Exception:
        upd_type = "unknown"
    log.exception("Unhandled error (%s): %r", upd_type, exception)
    try:
        cb = event.update.callback_query
        if cb:
            await cb.answer("Произошла ошибка. Попробуйте ещё раз.", show_alert=False)
    except Exception:
        pass

# ============ FASTAPI ============
@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.post("/webhooks/telegram")
async def telegram_webhook(req: Request) -> Response:
    data = await req.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return Response(status_code=200)
