from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

import config
from keyboards import (
    BTN_BY_AMO_ID,
    BTN_FROM_SCRATCH,
    BTN_HELP,
    BTN_CANCEL,
    get_help_text,
    get_main_keyboard,
    get_company_keyboard,
)
from states import FolderCreation

router = Router()


def get_user_company_access(user_id: int) -> str | None:
    if user_id in config.ALLOWED_BOTH:
        return "both"
    if user_id in config.ALLOWED_BLASTER:
        return "blaster"
    if user_id in config.ALLOWED_CULT:
        return "cult"
    return None


def get_allowed_companies(user_id: int) -> list[str]:
    access = get_user_company_access(user_id)
    if access == "both":
        return ["blaster", "cult"]
    if access:
        return [access]
    return []


def format_company_name(company: str) -> str:
    return "Бластер" if company == "blaster" else "Культ"


async def send_start_message(message: types.Message, allowed: list[str]):
    companies_hint = ", ".join(format_company_name(c) for c in allowed)
    await message.answer(
        "<b>Привет!</b> Я помогу создать единую систему папок и проектов.\n\n"
        f"<b>Доступные компании:</b> {companies_hint}\n\n"
        "Выбери сценарий кнопкой ниже или просто отправь ID сделки / название проекта.\n\n"
        "Нажми кнопку <b>❓ Помощь</b>, чтобы увидеть все команды.",
        parse_mode="HTML",
        reply_markup=get_main_keyboard(),
    )


async def _edit_or_answer(message: types.Message, text: str, **kwargs):
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest:
        await message.answer(text, **kwargs)


async def _start_mode(message: types.Message, state: FSMContext, mode: str):
    await state.clear()
    user_id = message.from_user.id
    allowed = get_allowed_companies(user_id)

    if not allowed:
        await message.answer("🚫 У вас нет доступа к этому боту.")
        return

    await state.update_data(creation_mode=mode)

    if len(allowed) == 1:
        await state.update_data(pending_company=allowed[0])
        company_name = format_company_name(allowed[0])
        if mode == "by_amo_id":
            text = (
                f"<b>📋 Создание по ID сделки Amo</b>\n"
                f"Компания: <b>{company_name}</b>\n\n"
                "Отправь ID сделки из AmoCRM:"
            )
        else:
            text = (
                f"<b>✨ Создание проекта с нуля</b>\n"
                f"Компания: <b>{company_name}</b>\n\n"
                "Отправь название проекта:"
            )
        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )
        await state.set_state(FolderCreation.editing_name)
        return

    mode_label = "по ID сделки Amo" if mode == "by_amo_id" else "с нуля"
    await message.answer(
        f"Выбери компанию для создания <b>{mode_label}</b>:",
        reply_markup=get_company_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(FolderCreation.choosing_company)


@router.message(Command("start", "help"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    allowed = get_allowed_companies(user_id)

    if not allowed:
        await message.answer("🚫 У вас нет доступа к этому боту.")
        return

    if message.text and message.text.startswith("/help"):
        await message.answer(
            get_help_text(allowed),
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )
        return

    await send_start_message(message, allowed)


@router.message(F.text == BTN_HELP)
async def cmd_help_button(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    allowed = get_allowed_companies(user_id)

    if not allowed:
        await message.answer("🚫 У вас нет доступа к этому боту.")
        return

    await message.answer(
        get_help_text(allowed),
        parse_mode="HTML",
        reply_markup=get_main_keyboard(),
    )


@router.message(F.text == BTN_CANCEL)
async def cancel_button(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    allowed = get_allowed_companies(user_id)

    if not allowed:
        await message.answer("🚫 У вас нет доступа к этому боту.")
        return

    await state.clear()
    await message.answer(
        "❌ Действие отменено.\n\nВыбери сценарий кнопкой ниже или /start.",
        reply_markup=get_main_keyboard(),
    )


@router.message(F.text == BTN_BY_AMO_ID)
async def mode_by_amo_id(message: types.Message, state: FSMContext):
    await _start_mode(message, state, "by_amo_id")


@router.message(F.text == BTN_FROM_SCRATCH)
async def mode_from_scratch(message: types.Message, state: FSMContext):
    await _start_mode(message, state, "from_scratch")


@router.callback_query(F.data == "nav:cancel")
async def nav_cancel(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    allowed = get_allowed_companies(user_id)
    await callback.answer()
    await state.clear()

    if not allowed:
        await _edit_or_answer(callback.message, "🚫 У вас нет доступа к этому боту.")
        return

    await _edit_or_answer(callback.message, "❌ Действие отменено.")
    await callback.message.answer(
        "Выбери сценарий кнопкой ниже или /start.",
        reply_markup=get_main_keyboard(),
    )


@router.callback_query(F.data == "nav:back")
async def nav_back(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    allowed = get_allowed_companies(user_id)
    user_data = await state.get_data()
    current_state = await state.get_state()
    await callback.answer()

    if not allowed:
        await _edit_or_answer(callback.message, "🚫 У вас нет доступа к этому боту.")
        return

    if (
        current_state == FolderCreation.editing_name.state
        and user_data.get("pending_company")
        and len(allowed) > 1
    ):
        mode = user_data.get("creation_mode", "")
        mode_label = "по ID сделки Amo" if mode == "by_amo_id" else "с нуля"
        await state.set_state(FolderCreation.choosing_company)
        await state.update_data(pending_company=None)
        await _edit_or_answer(
            callback.message,
            f"Выбери компанию для создания <b>{mode_label}</b>:",
            reply_markup=get_company_keyboard(),
            parse_mode="HTML",
        )
        return

    await state.clear()
    await _edit_or_answer(callback.message, "◀️ Возвращаю в главное меню.")
    await send_start_message(callback.message, allowed)
