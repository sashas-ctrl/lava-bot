import os
import logging
from typing import Dict, List, Tuple

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

PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")  # например https://<render-domain>
CHANNEL_ID = os.getenv("CHANNEL_ID", "")  # если где-то нужен числовой id (не обязателен здесь)

# экран «Что внутри?» — копируем пост из публичного канала
INSIDE_CHANNEL = os.getenv("INSIDE_CHANNEL", "")      # например: @greycomunity
INSIDE_POST_ID = int(os.getenv("INSIDE_POST_ID", "0"))  # например: 5

# Поддержка
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "sashablogerr")  # без @

# Тариф
TARIFF_PRICE = int(os.getenv("TARIFF_PRICE", "1499"))
TARIFF_DAYS = int(os.getenv("TARIFF_DAYS", "30"))

# Оплата картой РФ — пока это просто ссылка на страницу ЮKassa (Short Link / Custom form / магазин)
YOOKASSA_URL = os.getenv("YOOKASSA_URL", "https://pay.yookassa.ru/")  # поставь свою рабочую ссылку!

# Грейс-период (если используешь в другом месте), можно не трогать
GRACE_HOURS = int(os.getenv("GRACE_HOURS", "24"))

# ----------------------------- БОТ ----------------------------------
bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# ----------------------------- НАВИГАЦИЯ/ИСТОРИЯ --------------------
# Храним стек сообщений для удаления и возврата «Назад»
# user_id -> список message_id (последний = текущий экран)
user_history: Dict[int, List[int]] = {}

def remember_message(user_id: int, message_id: int):
    stack = user_history.setdefault(user_id, [])
    stack.append(message_id)

async def delete_prev_if_any(user_id: int, keep_last: int = 0):
    """
    Удаляем предыдущие сообщения пользователя, оставляя `keep_last` последних в истории.
    По умолчанию удалим предыдущее одно сообщение.
    """
    stack = user_history.get(user_id, [])
    while len(stack) > keep_last:
        mid = stack.pop()
        try:
            await bot.delete_message(user_id, mid)
        except Exception:
            pass

async def go_back(user_id: int):
    """
    «Назад» — удаляем текущее сообщение и возвращаемся к предыдущему экрану.
    """
    stack = user_history.get(user_id, [])
    # удаляем текущее
    if stack:
        try:
            await bot.delete_message(user_id, stack.pop())
        except Exception:
            pass
    # предыдущий просто остаётся на экране — ничего дополнительно не шлём


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

def kb_pay_card() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Оплатить {TARIFF_PRICE} ₽ / {TARIFF_DAYS} дней", url=YOOKASSA_URL)],
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


# ----------------------------- ХЕЛПЕРЫ ПО ЭКРАНАМ -------------------
async def send_screen_main(chat_id: int) -> None:
    # удаляем предыдущее сообщение (если было)
    await delete_prev_if_any(chat_id)
    msg = await bot.send_message(chat_id, WELCOME_TEXT, reply_markup=kb_main())
    remember_message(chat_id, msg.message_id)

async def send_screen_join(chat_id: int) -> None:
    await delete_prev_if_any(chat_id)
    msg = await bot.send_message(chat_id, JOIN_TEXT, reply_markup=kb_join())
    remember_message(chat_id, msg.message_id)

async def send_screen_pay_card(chat_id: int) -> None:
    await delete_prev_if_any(chat_id)
    msg = await bot.send_message(chat_id, PAY_CARD_TEXT, reply_markup=kb_pay_card())
    remember_message(chat_id, msg.message_id)

async def send_screen_pay_crypto(chat_id: int) -> None:
    await delete_prev_if_any(chat_id)
    msg = await bot.send_message(chat_id, PAY_CRYPTO_TEXT, reply_markup=kb_pay_crypto())
    remember_message(chat_id, msg.message_id)

async def send_inside(chat_id: int) -> None:
    """
    Копируем пост из публичного канала и ниже — наши кнопки.
    """
    await delete_prev_if_any(chat_id)
    # копируем сам пост
    if INSIDE_CHANNEL and INSIDE_POST_ID > 0:
        try:
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=INSIDE_CHANNEL,
                message_id=INSIDE_POST_ID
            )
        except Exception as e:
            log.warning(f"copy_message failed: {e}")
            # если не удалось — дадим краткое описание
            fallback = (
                "<b>Что внутри TubeComy?</b>\n\n"
                "✔️ Материалы по росту каналов\n"
                "✔️ Разборы и шаблоны\n"
                "✔️ Поддержка команды\n"
                f"Подписка: {TARIFF_PRICE} ₽ / {TARIFF_DAYS} дней"
            )
            m1 = await bot.send_message(chat_id, fallback)
            remember_message(chat_id, m1.message_id)
        else:
            # копирование прошло — просто пометим «виртуальный» id для стека
            # (сам пост удалить не сможем, т.к. он «чужой», поэтому управляем только нашим нижним сообщением)
            pass

    # под постом своё сообщение с клавиатурой
    footer = await bot.send_message(chat_id, "Выберите действие 👇", reply_markup=kb_inside_footer())
    remember_message(chat_id, footer.message_id)

# ----------------------------- ХЕНДЛЕРЫ -----------------------------
@dp.message(F.text == "/start")
async def cmd_start(m: Message):
    # сбросим историю, начнём с нуля
    user_history[m.from_user.id] = []
    await send_screen_main(m.chat.id)

@dp.callback_query(F.data == "join")
async def cb_join(cb: CallbackQuery):
    await send_screen_join(cb.from_user.id)
    await cb.answer()

@dp.callback_query(F.data == "pay_card")
async def cb_pay_card(cb: CallbackQuery):
    await send_screen_pay_card(cb.from_user.id)
    await cb.answer()

@dp.callback_query(F.data == "pay_crypto")
async def cb_pay_crypto(cb: CallbackQuery):
    await send_screen_pay_crypto(cb.from_user.id)
    await cb.answer()

@dp.callback_query(F.data == "inside")
async def cb_inside(cb: CallbackQuery):
    await send_inside(cb.from_user.id)
    await cb.answer()

@dp.callback_query(F.data == "back")
async def cb_back(cb: CallbackQuery):
    await go_back(cb.from_user.id)
    await cb.answer()

@dp.callback_query(F.data == "back_join")
async def cb_back_join(cb: CallbackQuery):
    # удаляем текущее и показываем экран выбора оплаты
    await go_back(cb.from_user.id)
    await send_screen_join(cb.from_user.id)
    await cb.answer()

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

# устанавливаем вебхук при старте
@app.on_event("startup")
async def on_startup():
    if PUBLIC_URL:
        url = f"{PUBLIC_URL}/webhooks/telegram"
        await bot.set_webhook(url)
        log.info(f"Webhook set to {url}")
    else:
        log.warning("PUBLIC_URL not set — webhook won't be installed")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()
