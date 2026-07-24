import os
import asyncio
import logging
from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from drive_service import get_drive_service, create_drive_folder, create_folders_recursive, send_webhook, send_cup_webhook
import config
from states import FolderCreation
from ai_service import analyze_user_intent, transcribe_voice
from amo_service import extract_deal_id, get_deal_name, create_deal, get_deal_link
from aiogram.filters import StateFilter
from keyboards import get_main_keyboard

router = Router()

CULT_STRUCTURE = {
    "1 - Presale": ["Brief", "Creative"],
    "2 - Project": [
        "00 - Brief", "01 - Script", "03 - Casting", "04 - Wardrobe",
        "05 - Locations", "06 - Props", "07 - Edit", "12 - pre-PPM-PPM",
        "13 - Timing", "15 - Administration", "16 - PR", "17 - Safety"
    ],
    "3 - Documents": {
        "Docs": ["Client", "Team"],
        "Money": ["CE"]
    }
}

BLASTER_STRUCTURE = {
    "1 - PROJECT": [
        "01_Client", "02_Script, Concepts", "03_Timing", "04_Animatic",
        "05_Creative", "06_Sound", "07_Design and Illustration",
        "08_Animation and Motion", "11_Client_preview"
    ],
    "2 - DOCUMENTS": {
        "Docs": ["Client", "Team"],
        "Money": []
    },
    "3 - CASE": []
}


def get_allowed_companies_for_user(user_id: int) -> list:
    if user_id in config.ALLOWED_BOTH:
        return ["blaster", "cult"]
    if user_id in config.ALLOWED_BLASTER:
        return ["blaster"]
    if user_id in config.ALLOWED_CULT:
        return ["cult"]
    return []


def get_confirmation_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm:yes")
    builder.button(text="✏️ Изменить", callback_data="confirm:edit")
    builder.button(text="❌ Отмена", callback_data="confirm:cancel")
    builder.adjust(1, 2)
    return builder.as_markup()


def format_company_name(company: str) -> str:
    return "Бластер" if company == "blaster" else "Культ"


def format_confirmation_text(
    company: str,
    folder_name: str,
    deal_id: str | None = None,
    create_amo: bool = False,
) -> str:
    company_name = format_company_name(company)
    text = (
        f"<b>Подтвердите создание проекта:</b>\n\n"
        f"<b>Компания:</b> {company_name}\n"
    )
    if deal_id:
        text += f"<b>Сделка AmoCRM:</b> #{deal_id}\n"
    elif create_amo:
        text += "<b>AmoCRM:</b> будет создана новая сделка\n"
    text += f"<b>Имя папки:</b> {folder_name}\n\n"
    text += (
        "<i>Будут созданы: Google Drive → "
        f"{'СнупДок' if company == 'blaster' else 'Нори'} → ЦУП</i>"
    )
    return text


async def resolve_folder_name(user_text: str, allowed: list) -> tuple[str | None, str | None, str | None]:
    deal_id = extract_deal_id(user_text)
    intent = await analyze_user_intent(user_text, allowed)
    company = intent.get("company")

    if deal_id:
        company_hint = company if company in allowed else None
        if not company_hint and len(allowed) == 1:
            company_hint = allowed[0]

        folder_name = await get_deal_name(deal_id, company_hint)
        if not folder_name:
            return None, company, deal_id
        return folder_name, company, deal_id

    return intent.get("folder_name"), company, None


async def show_confirmation(
    message: types.Message,
    state: FSMContext,
    company: str,
    folder_name: str,
    deal_id: str | None = None,
    create_amo: bool = False,
):
    await state.update_data(
        pending_company=company,
        pending_folder_name=folder_name,
        pending_deal_id=deal_id,
        pending_create_amo=create_amo and not deal_id,
    )
    await message.answer(
        format_confirmation_text(company, folder_name, deal_id, create_amo and not deal_id),
        reply_markup=get_confirmation_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(FolderCreation.confirm_creation)


async def execute_folder_creation(
    message: types.Message,
    company: str,
    folder_name: str,
    deal_id: str | None = None,
    create_amo: bool = False,
):
    status_message = await message.answer(
        f"⏳ Запускаю создание проекта для {format_company_name(company)}...",
        reply_markup=get_main_keyboard(),
    )

    if create_amo and not deal_id:
        await status_message.edit_text("⏳ Создаю сделку в AmoCRM...")
        deal_id = await create_deal(folder_name, company)
        if not deal_id:
            await status_message.edit_text(
                "❌ Не удалось создать сделку в AmoCRM. Проверь токен и ID воронки в .env."
            )
            return

    await status_message.edit_text("⏳ Создаю структуру папок на Google Drive...")

    parent_id = config.PARENT_FOLDER_BLASTER if company == "blaster" else config.PARENT_FOLDER_CULT
    structure = BLASTER_STRUCTURE if company == "blaster" else CULT_STRUCTURE

    try:
        service = await asyncio.to_thread(get_drive_service, company)

        main_folder = await asyncio.to_thread(create_drive_folder, service, folder_name, parent_id)
        main_folder_id = main_folder.get("id")
        main_folder_link = main_folder.get("webViewLink")

        await asyncio.to_thread(create_folders_recursive, service, structure, main_folder_id)

        await status_message.edit_text("⏳ Регистрирую проект в системах...")

        project_uuid, internal_project_link = await send_webhook(
            company=company,
            folder_name=folder_name,
            folder_link=main_folder_link,
            folder_id=main_folder_id,
            deal_id=deal_id,
        )

        cup_project_link = await send_cup_webhook(
            company=company,
            folder_name=folder_name,
            folder_link=main_folder_link,
            folder_id=main_folder_id,
            project_id=project_uuid,
            deal_id=deal_id,
        )

        internal_system_name = "СнупДок" if company == "blaster" else "Нори"

        links_text = f"• <a href='{main_folder_link}'>Google Диск</a>\n"
        if cup_project_link:
            links_text += f"• <a href='{cup_project_link}'>Проект в ЦУП</a>\n"
        if internal_project_link:
            links_text += f"• <a href='{internal_project_link}'>Проект в {internal_system_name}</a>\n"
        if deal_id:
            amo_link = get_deal_link(deal_id, company)
            if amo_link:
                links_text += f"• <a href='{amo_link}'>Сделка в AmoCRM</a>\n"

        warnings = []
        webhook_url = config.WEBHOOK_URL_CULT if company == "cult" else config.WEBHOOK_URL_BLASTER
        if not project_uuid and webhook_url:
            warnings.append(f"не удалось зарегистрировать проект в {internal_system_name}")
        if not cup_project_link and config.WEBHOOK_URL_CUP:
            warnings.append("не удалось зарегистрировать проект в ЦУП")

        warning_text = f"\n\n⚠️ <i>Папки созданы, но: {', '.join(warnings)}.</i>" if warnings else ""
        deal_text = f"\n<b>Сделка AmoCRM:</b> #{deal_id}" if deal_id else ""

        await status_message.edit_text(
            f"<b>✅ Проект создан — {format_company_name(company)}</b>\n\n"
            f"<b>Папка:</b> {folder_name}{deal_text}\n\n"
            f"🔗 <b>Ссылки:</b>\n{links_text}{warning_text}",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    except Exception as e:
        logging.error(f"Ошибка создания папок или отправки вебхука: {e}")
        await status_message.edit_text("❌ Произошла ошибка при создании. Проверьте логи.")


async def _prompt_after_company(callback: types.CallbackQuery, state: FSMContext, company: str):
    user_data = await state.get_data()
    mode = user_data.get("creation_mode")
    folder_name = user_data.get("pending_folder_name")
    deal_id = user_data.get("pending_deal_id")
    company_name = format_company_name(company)

    if folder_name:
        create_amo = mode == "from_scratch" and not deal_id
        await callback.message.edit_text(
            format_confirmation_text(company, folder_name, deal_id, create_amo),
            reply_markup=get_confirmation_keyboard(),
            parse_mode="HTML",
        )
        await state.update_data(pending_company=company, pending_create_amo=create_amo)
        await state.set_state(FolderCreation.confirm_creation)
        return

    if mode == "by_amo_id":
        text = (
            f"Компания: <b>{company_name}</b>\n\n"
            "Отправь <b>ID сделки</b> из AmoCRM:"
        )
    elif mode == "from_scratch":
        text = (
            f"Компания: <b>{company_name}</b>\n\n"
            "Отправь <b>название проекта</b>.\n"
            "Бот создаст сделку в AmoCRM и дальше всё по цепочке."
        )
    else:
        text = (
            f"Компания: <b>{company_name}</b>\n\n"
            "Отправь <b>ID сделки Amo</b> или <b>название проекта</b>:"
        )

    await callback.message.edit_text(text, parse_mode="HTML")
    await state.update_data(pending_company=company)
    await state.set_state(FolderCreation.editing_name)


@router.message(StateFilter(None), F.voice | F.text)
async def handle_user_request(message: types.Message, state: FSMContext, bot: Bot):
    if message.text and message.text.startswith("/"):
        return

    user_id = message.from_user.id
    allowed = get_allowed_companies_for_user(user_id)

    if not allowed:
        await message.answer("🚫 У вас нет доступа к этому боту.")
        return

    if message.voice:
        voice_file = await bot.get_file(message.voice.file_id)
        file_path = f"voice_{message.voice.file_id}.ogg"
        await bot.download_file(voice_file.file_path, file_path)
        user_text = await transcribe_voice(file_path)
        if os.path.exists(file_path):
            os.remove(file_path)
        if not user_text:
            await message.answer("❌ Не удалось разобрать голосовое сообщение.")
            return
    else:
        user_text = message.text.strip()

    deal_id = extract_deal_id(user_text)

    if deal_id:
        await message.answer(f"🔍 Ищу сделку #{deal_id} в AmoCRM...")
        folder_name, company, deal_id = await resolve_folder_name(user_text, allowed)
        create_amo = False

        if not folder_name:
            await message.answer(
                f"❌ Не удалось найти сделку с ID <b>{deal_id}</b> в AmoCRM.\n"
                "Проверь ID и воронку компании.",
                parse_mode="HTML",
            )
            return
    else:
        intent = await analyze_user_intent(user_text, allowed)
        folder_name = intent.get("folder_name")
        company = intent.get("company")
        deal_id = None
        create_amo = True

        if not folder_name:
            await message.answer(
                "🤖 Не понял название проекта.\n\n"
                "Отправь название, ID сделки Amo или выбери сценарий кнопкой ниже.",
                reply_markup=get_main_keyboard(),
            )
            return

    if company in allowed:
        await show_confirmation(message, state, company, folder_name, deal_id, create_amo)
    elif len(allowed) == 1:
        await show_confirmation(message, state, allowed[0], folder_name, deal_id, create_amo)
    else:
        await state.update_data(
            pending_folder_name=folder_name,
            pending_deal_id=deal_id,
            pending_create_amo=create_amo,
            creation_mode="from_scratch" if create_amo else "by_amo_id",
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="Бластер", callback_data="ai_company:blaster")
        builder.button(text="Культ", callback_data="ai_company:cult")
        builder.adjust(2)

        scenario = "с нуля (новая сделка в Amo)" if create_amo else f"по сделке #{deal_id}"
        await message.answer(
            f"Создание <b>{scenario}</b>:\n"
            f"Папка <b>«{folder_name}»</b>\n\n"
            "Выбери компанию:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        await state.set_state(FolderCreation.choosing_company)


@router.callback_query(F.data.startswith("ai_company:") | F.data.startswith("company:"))
async def ai_company_chosen(callback: types.CallbackQuery, state: FSMContext):
    company = callback.data.split(":")[1]
    await _prompt_after_company(callback, state, company)
    await callback.answer()


@router.callback_query(FolderCreation.confirm_creation, F.data.startswith("confirm:"))
async def process_confirmation(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()

    action = callback.data.split(":")[1]
    user_data = await state.get_data()
    company = user_data.get("pending_company")
    folder_name = user_data.get("pending_folder_name")
    deal_id = user_data.get("pending_deal_id")
    create_amo = user_data.get("pending_create_amo", False)

    if action == "yes":
        await callback.message.delete()
        await state.clear()
        await execute_folder_creation(
            callback.message, company, folder_name, deal_id, create_amo
        )
    elif action == "edit":
        await callback.message.edit_text(
            "✏️ Отправь новое название или ID сделки Amo:",
        )
        await state.set_state(FolderCreation.editing_name)
    elif action == "cancel":
        await callback.message.edit_text("❌ Создание отменено.")
        await state.clear()


@router.message(FolderCreation.editing_name)
async def process_new_name(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Отправь текстовое сообщение.")
        return

    user_text = message.text.strip()
    user_data = await state.get_data()
    company = user_data.get("pending_company")
    mode = user_data.get("creation_mode")

    if not company:
        await message.answer("❌ Компания не выбрана. Нажми /start.")
        await state.clear()
        return

    deal_id = extract_deal_id(user_text)

    if mode == "by_amo_id":
        if not deal_id:
            await message.answer("❌ В этом режиме нужен ID сделки AmoCRM (число).")
            return
        await message.answer(f"🔍 Ищу сделку #{deal_id} в AmoCRM...")
        folder_name = await get_deal_name(deal_id, company)
        if not folder_name:
            await message.answer(
                f"❌ Сделка <b>{deal_id}</b> не найдена или из другой воронки.",
                parse_mode="HTML",
            )
            return
        create_amo = False
    elif mode == "from_scratch":
        if deal_id:
            await message.answer("❌ В режиме «с нуля» отправь название, а не ID.")
            return
        folder_name = user_text
        deal_id = None
        create_amo = True
    elif deal_id:
        await message.answer(f"🔍 Ищу сделку #{deal_id} в AmoCRM...")
        folder_name = await get_deal_name(deal_id, company)
        if not folder_name:
            await message.answer(
                f"❌ Сделка <b>{deal_id}</b> не найдена или из другой воронки.",
                parse_mode="HTML",
            )
            return
        create_amo = False
    else:
        folder_name = user_text
        deal_id = None
        create_amo = True

    await show_confirmation(message, state, company, folder_name, deal_id, create_amo)
