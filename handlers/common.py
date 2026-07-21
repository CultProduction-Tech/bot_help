from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from states import FolderCreation

router = Router()

def get_user_company_access(user_id: int) -> str | None:
    if user_id in config.ALLOWED_BOTH:
        return "both"
    elif user_id in config.ALLOWED_BLASTER:
        return "blaster"
    elif user_id in config.ALLOWED_CULT:
        return "cult"
    return None

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    access = get_user_company_access(user_id)

    if not access:
        await message.answer("🚫 У вас нет доступа к этому боту.")
        return

    if access == "both":
        builder = InlineKeyboardBuilder()
        builder.button(text="Бластер", callback_data="company:blaster")
        builder.button(text="Культ", callback_data="company:cult")
        builder.adjust(2)
        
        await message.answer(
            "Привет! Ты авторизован для обеих компаний. Выбери, где создать папку:",
            reply_markup=builder.as_markup()
        )
        await state.set_state(FolderCreation.choosing_company)
    else:
        company_name = "Бластер" if access == "blaster" else "Культ"
        await state.update_data(pending_company=access)
        
        await message.answer(
            f"Привет! Создаем папку для компании **{company_name}**.\n\n"
            "Введите **название папки** или **ID сделки из AmoCRM**:",
            parse_mode="Markdown"
        )
        await state.set_state(FolderCreation.editing_name)