# --- ХЕНДЛЕРЫ callback-кнопок (обновлённые) ---

@dp.callback_query(F.data == "join")
async def cb_join(cb: CallbackQuery):
    # Убираем "крутилку" сразу, затем отрисовываем экран
    await cb.answer()
    try:
        email = get_email(cb.from_user.id)
        if email:
            # e-mail уже известен -> сразу выбор способа оплаты
            await show_screen(cb.from_user.id, "join")
        else:
            # спрашиваем e-mail один раз
            await show_screen(cb.from_user.id, "email")
    except Exception as e:
        logging.exception("cb_join failed: %s", e)
        await bot.send_message(cb.from_user.id, "Не удалось открыть раздел. Попробуйте /start")

@dp.callback_query(F.data == "pay_card")
async def cb_pay_card(cb: CallbackQuery):
    await cb.answer()
    try:
        await show_screen(cb.from_user.id, "pay_card")
    except Exception as e:
        logging.exception("cb_pay_card failed: %s", e)
        await bot.send_message(cb.from_user.id, "Не удалось открыть оплату картой. Попробуйте /start")

@dp.callback_query(F.data == "pay_crypto")
async def cb_pay_crypto(cb: CallbackQuery):
    await cb.answer()
    try:
        await show_screen(cb.from_user.id, "pay_crypto")
    except Exception as e:
        logging.exception("cb_pay_crypto failed: %s", e)
        await bot.send_message(cb.from_user.id, "Не удалось открыть раздел криптооплаты. Попробуйте /start")

@dp.callback_query(F.data == "inside")
async def cb_inside(cb: CallbackQuery):
    await cb.answer()
    try:
        await show_screen(cb.from_user.id, "inside")
    except Exception as e:
        logging.exception("cb_inside failed: %s", e)
        await bot.send_message(cb.from_user.id, "Не удалось показать пост. Попробуйте /start")

@dp.callback_query(F.data == "back")
async def cb_back(cb: CallbackQuery):
    await cb.answer()
    try:
        # универсальный "назад": вернёмся на пред. экран, либо на main
        await back_screen(cb.from_user.id, fallback_name="main")
    except Exception as e:
        logging.exception("cb_back failed: %s", e)
        await bot.send_message(cb.from_user.id, "Не удалось вернуться назад. Попробуйте /start")

# Если у тебя есть отдельная кнопка "назад" внутри экрана выбора оплаты:
@dp.callback_query(F.data == "back_join")
async def cb_back_join(cb: CallbackQuery):
    await cb.answer()
    try:
        await show_screen(cb.from_user.id, "join")
    except Exception as e:
        logging.exception("cb_back_join failed: %s", e)
        await bot.send_message(cb.from_user.id, "Не удалось вернуться к выбору оплаты. Попробуйте /start")
