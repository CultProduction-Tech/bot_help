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
from amo_service import extract_deal_id, get_deal_name
from aiogram.filters import StateFilter
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
    elif user_id in config.ALLOWED_BLASTER:
        return ["blaster"]
    elif user_id in config.ALLOWED_CULT:
        return ["cult"]
    return []

def get_confirmation_keyboard():
    """Создает клавиатуру подтверждения запроса."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm:yes")
    builder.button(text="✏️ Изменить имя", callback_data="confirm:edit")
    builder.button(text="❌ Отмена", callback_data="confirm:cancel")
    builder.adjust(1, 2)
    return builder.as_markup()


def format_company_name(company: str) -> str:
    return "Бластер" if company == "blaster" else "Культ"


def format_confirmation_text(company: str, folder_name: str, deal_id: str | None = None) -> str:
    company_name = format_company_name(company)
    text = (
        f"<b>Подтвердите создание папки:</b>\n\n"
        f"<b>Компания:</b> {company_name}\n"
    )
    if deal_id:
        text += f"<b>Сделка AmoCRM:</b> #{deal_id}\n"
    text += f"<b>Имя папки:</b> {folder_name}"
    return text


async def resolve_folder_name(user_text: str, allowed: list) -> tuple[str | None, str | None, str | None]:
    """
    Определяет имя папки из текста или AmoCRM.
    Возвращает (folder_name, company, deal_id).
    """
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


async def show_confirmation(message: types.Message, state: FSMContext, company: str, folder_name: str, deal_id: str | None = None):
    await state.update_data(
        pending_company=company,
        pending_folder_name=folder_name,
        pending_deal_id=deal_id,
    )
    await message.answer(
        format_confirmation_text(company, folder_name, deal_id),
        reply_markup=get_confirmation_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(FolderCreation.confirm_creation)

async def execute_folder_creation(message: types.Message, company: str, folder_name: str, deal_id: str | None = None):
    """Непосредственное создание структуры папок."""
    status_message = await message.answer(f"Создаю структуру папок для {company.upper()}...")
    
    parent_id = config.PARENT_FOLDER_BLASTER if company == "blaster" else config.PARENT_FOLDER_CULT
    structure = BLASTER_STRUCTURE if company == "blaster" else CULT_STRUCTURE
    
    try:
        service = await asyncio.to_thread(get_drive_service, company)
        
        main_folder = await asyncio.to_thread(create_drive_folder, service, folder_name, parent_id)
        main_folder_id = main_folder.get('id')
        main_folder_link = main_folder.get('webViewLink')
        
        await asyncio.to_thread(create_folders_recursive, service, structure, main_folder_id)

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

        warnings = []
        webhook_url = config.WEBHOOK_URL_CULT if company == "cult" else config.WEBHOOK_URL_BLASTER
        if not project_uuid and webhook_url:
            warnings.append(f"не удалось зарегистрировать проект в {internal_system_name}")
        if not cup_project_link and config.WEBHOOK_URL_CUP:
            warnings.append("не удалось зарегистрировать проект в ЦУП")

        warning_text = ""
        if warnings:
            warning_text = f"\n\n⚠️ <i>Папки созданы, но: {', '.join(warnings)}.</i>"

        deal_text = f"\n<b>Сделка AmoCRM:</b> #{deal_id}" if deal_id else ""

        await status_message.edit_text(
            f"<b>Успешно создано для компании {company}:</b>\n\n"
            f"<b>Папка проекта:</b> {folder_name}{deal_text}\n\n"
            f"🔗 <b>Ссылки на ресурсы:</b>\n"
            f"{links_text}{warning_text}",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logging.error(f"Ошибка создания папок или отправки вебхука: {e}")
        await status_message.edit_text("❌ Произошла ошибка при создании папок Google Drive. Проверьте логи.")

# --- ОБРАБОТКА ТЕКСТА И ГОЛОСА ---

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

    deal_id_hint = extract_deal_id(user_text)
    if deal_id_hint:
        await message.answer(f"🔍 Ищу сделку #{deal_id_hint} в AmoCRM...")

    folder_name, company, deal_id = await resolve_folder_name(user_text, allowed)

    if deal_id and not folder_name:
        await message.answer(
            f"❌ Не удалось найти сделку с ID <b>{deal_id}</b> в AmoCRM.\n"
            "Проверь ID или настройки AmoCRM в .env.",
            parse_mode="HTML",
        )
        return

    if not folder_name:
        await message.answer(
            "🤖 Я понял, что ты хочешь создать папку, но не смог выделить её имя из контекста. "
            "Напиши название, ID сделки AmoCRM или скажи голосом."
        )
        return

    if company in allowed:
        await show_confirmation(message, state, company, folder_name, deal_id)
    elif len(allowed) == 1:
        await show_confirmation(message, state, allowed[0], folder_name, deal_id)
    else:
        await state.update_data(pending_folder_name=folder_name, pending_deal_id=deal_id)
        
        builder = InlineKeyboardBuilder()
        builder.button(text="Бластер", callback_data="ai_company:blaster")
        builder.button(text="Культ", callback_data="ai_company:cult")
        builder.adjust(2)
        
        deal_info = f" (сделка #{deal_id})" if deal_id else ""
        await message.answer(
            f"Я понял, что нужно создать папку <b>\"{folder_name}\"</b>{deal_info}.\n"
            f"На каком Google Диске её разместить?",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.set_state(FolderCreation.choosing_company)

@router.callback_query(F.data.startswith("ai_company:") | F.data.startswith("company:"))
async def ai_company_chosen(callback: types.CallbackQuery, state: FSMContext):
    company = callback.data.split(":")[1]
    user_data = await state.get_data()
    folder_name = user_data.get("pending_folder_name")
    deal_id = user_data.get("pending_deal_id")
    
    await state.update_data(pending_company=company)
    company_name = format_company_name(company)
    
    if folder_name:
        await callback.message.edit_text(
            format_confirmation_text(company, folder_name, deal_id),
            reply_markup=get_confirmation_keyboard(),
            parse_mode="HTML"
        )
        await state.set_state(FolderCreation.confirm_creation)
    else:
        await callback.message.edit_text(
            f"Выбрана компания: <b>{company_name}</b>.\n\n"
            f"Введите <b>название папки</b> или <b>ID сделки AmoCRM</b> ответным сообщением:",
            parse_mode="HTML"
        )
        await state.set_state(FolderCreation.editing_name)
        
    await callback.answer()

# --- ШАГ ПОДТВЕРЖДЕНИЯ (Кнопки) ---
@router.callback_query(FolderCreation.confirm_creation, F.data.startswith("confirm:"))
async def process_confirmation(callback: types.CallbackQuery, state: FSMContext):
    # 1. Сразу же отвечаем Телеграму, чтобы убрать анимацию загрузки на кнопке
    await callback.answer()
    
    action = callback.data.split(":")[1]
    user_data = await state.get_data()
    company = user_data.get("pending_company")
    folder_name = user_data.get("pending_folder_name")
    deal_id = user_data.get("pending_deal_id")
    
    if action == "yes":
        await callback.message.delete()
        await state.clear()
        await execute_folder_creation(callback.message, company, folder_name, deal_id)
        
    elif action == "edit":
        await callback.message.edit_text(
            "✏️ Введите новое название или ID сделки AmoCRM ответным сообщением:",
            parse_mode="Markdown"
        )
        await state.set_state(FolderCreation.editing_name)
        
    elif action == "cancel":
        await callback.message.edit_text("❌ Создание папки отменено.")
        await state.clear()
# --- ОБРАБОТКА ИЗМЕНЕНИЯ ИМЕНИ (Текст) ---
@router.message(FolderCreation.editing_name)
async def process_new_name(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Отправь текстовое сообщение с названием или ID сделки.")
        return

    user_text = message.text.strip()
    user_data = await state.get_data()
    company = user_data.get("pending_company")

    if not company:
        await message.answer("❌ Компания не выбрана. Начните с команды /start.")
        await state.clear()
        return

    deal_id_hint = extract_deal_id(user_text)
    if deal_id_hint:
        await message.answer(f"🔍 Ищу сделку #{deal_id_hint} в AmoCRM...")
        folder_name = await get_deal_name(deal_id_hint, company)
        deal_id = deal_id_hint
        if not folder_name:
            await message.answer(
                f"❌ Не удалось найти сделку с ID <b>{deal_id_hint}</b> в AmoCRM.",
                parse_mode="HTML",
            )
            return
    else:
        folder_name = user_text
        deal_id = None

    await state.update_data(pending_folder_name=folder_name, pending_deal_id=deal_id)
    company_name = format_company_name(company)

    title = "Имя изменено! Подтвердите создание:" if user_data.get("pending_folder_name") else "Подтвердите создание:"
    text = f"<b>{title}</b>\n\n<b>Компания:</b> {company_name}\n"
    if deal_id:
        text += f"<b>Сделка AmoCRM:</b> #{deal_id}\n"
    text += f"<b>Имя папки:</b> {folder_name}"

    await message.answer(
        text,
        reply_markup=get_confirmation_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(FolderCreation.confirm_creation)