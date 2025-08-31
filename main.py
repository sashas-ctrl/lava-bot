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

# ---------- UI ----------
from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

TARIFF_PRICE = int(os.getenv("TARIFF_PRICE", "1499"))
TARIFF_DAYS  = int(os.getenv("TARIFF_DAYS", "30"))
WHAT_INSIDE_URL = os.getenv("WHAT_INSIDE_URL", "")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "")

WELCOME_TEXT = (
    "Привет 👋\n\n"
    "Это закрытое сообщество. Оформите подписку и получите доступ в приватный канал."
)

def main_menu() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="ВСТУПИТЬ", callback_data="menu:join")],
    ]
    # Что внутри? — это сразу ссылка на твой пост
    if WHAT_INSIDE_URL:
        buttons.append([InlineKeyboardButton(text="Что внутри?", url=WHAT_INSIDE_URL)])
    else:
        buttons.append([InlineKeyboardButton(text="Что внутри?", callback_data="menu:inside")])
    # Задать вопрос — сразу диалог в Telegram
    if SUPPORT_USERNAME:
        buttons.append([InlineKeyboardButton(text="Задать вопрос", url=f"https://t.me/{SUPPORT_USERNAME}")])
    else:
        buttons.append([InlineKeyboardButton(text="Задать вопрос", callback_data="menu:support")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def tariffs_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{TARIFF_PRICE}₽ / {TARIFF_DAYS} дней", callback_data=f"plan:{TARIFF_PRICE}:{TARIFF_DAYS}")],
        [InlineKeyboardButton(text="◀︎ Назад", callback_data="menu:back")]
    ])

@dp.message(Command("start"))
async def on_start(m: Message):
    await m.answer(WELCOME_TEXT, reply_markup=main_menu())

@dp.callback_query(F.data == "menu:join")
async def menu_join(cq):
    await cq.message.edit_text("Выберите тариф 👇", reply_markup=tariffs_kb())
    await cq.answer()

@dp.callback_query(F.data.startswith("plan:"))
async def pick_plan(cq):
    # plan:<price>:<days>
    _, price, days = cq.data.split(":")
    # Если Лава настроена — создаём инвойс и даём ссылку
    if os.getenv("LAVA_API_BASE") and os.getenv("LAVA_API_KEY"):
        try:
            pay_url = await create_lava_invoice(
                tg_id=cq.from_user.id
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"Перейти к оплате ({price}₽ / {days} дней)", url=pay_url)],
                [InlineKeyboardButton(text="◀︎ Назад", callback_data="menu:join")]
            ])
            await cq.message.edit_text("Готово! Нажмите для оплаты 👇", reply_markup=kb)
        except Exception:
            await cq.message.edit_text(
                "Сейчас оплата недоступна. Попробуйте позже.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀︎ Назад", callback_data="menu:join")]
                ])
            )
    else:
        await cq.message.edit_text(
            "Оплата включится после модерации платёжного провайдера. Спасибо за ожидание 🙏",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀︎ Назад", callback_data="menu:join")]
            ])
        )
    await cq.answer()

@dp.callback_query(F.data == "menu:inside")
async def menu_inside(cq):
    await cq.message.edit_text(
        "Ссылка на описание ещё не указана. Добавь WHAT_INSIDE_URL в переменные окружения.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀︎ Назад", callback_data="menu:back")]
        ])
    )
    await cq.answer()

@dp.callback_query(F.data == "menu:support")
async def menu_support(cq):
    await cq.message.edit_text(
        "Укажи SUPPORT_USERNAME в переменных окружения, чтобы кнопка открывала личный чат.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀︎ Назад", callback_data="menu:back")]
        ])
    )
    await cq.answer()

@dp.callback_query(F.data == "menu:back")
async def menu_back(cq):
    await cq.message.edit_text(WELCOME_TEXT, reply_markup=main_menu())
    await cq.answer()
# ---------- /UI ----------

@app.post("/webhooks/telegram")
async def telegram_webhook(request: Request):
    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
