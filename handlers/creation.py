import os
import logging
from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from drive_service import get_drive_service, create_drive_folder, create_folders_recursive, send_webhook, send_cup_webhook
import config
from states import FolderCreation
from ai_service import analyze_user_intent, transcribe_voice

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
    builder.adjust(1, 2)  # Первая кнопка на всю ширину, две другие в один ряд
    return builder.as_markup()

async def execute_folder_creation(message: types.Message, company: str, folder_name: str):
    """Непосредственное создание структуры папок."""
    status_message = await message.answer(f"Создаю структуру папок для {company.upper()}...")
    
    parent_id = config.PARENT_FOLDER_BLASTER if company == "blaster" else config.PARENT_FOLDER_CULT
    structure = BLASTER_STRUCTURE if company == "blaster" else CULT_STRUCTURE
    
    try:
        service = get_drive_service(company)
        
        # 1. Создаем главную папку
        main_folder = create_drive_folder(service, folder_name, parent_id)
        main_folder_id = main_folder.get('id')
        main_folder_link = main_folder.get('webViewLink')
        
        # 2. Создаем структуру
        create_folders_recursive(service, structure, main_folder_id)

        project_uuid = await send_webhook(
            company=company,
            folder_name=folder_name,
            folder_link=main_folder_link,
            folder_id=main_folder_id
        )

        await send_cup_webhook(
            company=company,
            folder_name=folder_name,
            folder_link=main_folder_link,
            folder_id=main_folder_id,
            project_id=project_uuid
        )


        await status_message.edit_text(
            f"<b>Успешно создано для компании {company.upper()}!</b>\n\n"
            f"<b>Папка проекта:</b> {folder_name}\n"
            f"<a href='{main_folder_link}'>Открыть папку на Google Диске</a>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logging.error(f"Ошибка создания папок или отправки вебхука: {e}")
        await status_message.edit_text("❌ Произошла ошибка при создании папок Google Drive. Проверьте логи.")

# --- ОБРАБОТКА ТЕКСТА И ГОЛОСА ---

@router.message(F.voice | F.text)
async def handle_user_request(message: types.Message, state: FSMContext, bot: Bot):
    if message.text and message.text.startswith("/"):
        return

    # Защита: если мы уже находимся в каком-то состоянии FSM, игнорируем новые запросы
    current_state = await state.get_state()
    if current_state in [FolderCreation.confirm_creation, FolderCreation.editing_name]:
        return

    user_id = message.from_user.id
    allowed = get_allowed_companies_for_user(user_id)
    
    if not allowed:
        await message.answer("🚫 У вас нет доступа к этому боту.")
        return

    # 1. Извлекаем текст
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

    # 2. ИИ-анализ намерения
    intent = await analyze_user_intent(user_text, allowed)
    folder_name = intent.get("folder_name")
    company = intent.get("company")

    if not folder_name:
        await message.answer("🤖 Я понял, что ты хочешь создать папку, но не смог выделить её имя из контекста. Напиши или скажи ещё раз.")
        return

    # 3. Подготовка подтверждения
    if company in allowed:
        # Если ИИ определил и компанию, и имя папки
        await state.update_data(pending_company=company, pending_folder_name=folder_name)
        company_name = "Бластер" if company == "blaster" else "Культ"
        
        await message.answer(
            f"<b>Подтвердите создание папки:</b>\n\n"
            f"<b>Компания:</b> {company_name}\n"
            f"<b>Имя папки:</b> {folder_name}",
            reply_markup=get_confirmation_keyboard(),
            parse_mode="HTML"
        )
        await state.set_state(FolderCreation.confirm_creation)
        
    elif len(allowed) == 1:
        # Если компания неизвестна, но у юзера всего 1 доступная компания
        await state.update_data(pending_company=allowed[0], pending_folder_name=folder_name)
        company_name = "Бластер" if allowed[0] == "blaster" else "Культ"
        
        await message.answer(
            f"<b>Подтвердите создание папки:</b>\n\n"
            f"<b>Компания:</b> {company_name}\n"
            f"<b>Имя папки:</b> {folder_name}",
            reply_markup=get_confirmation_keyboard(),
            parse_mode="HTML"
        )
        await state.set_state(FolderCreation.confirm_creation)
        
    else:
        # Если компания неизвестна и юзер — админ в обеих (сначала даем выбрать компанию)
        await state.update_data(pending_folder_name=folder_name)
        
        builder = InlineKeyboardBuilder()
        builder.button(text="Бластер", callback_data="ai_company:blaster")
        builder.button(text="Культ", callback_data="ai_company:cult")
        builder.adjust(2)
        
        await message.answer(
            f"Я понял, что нужно создать папку <b>\"{folder_name}\"</b>.\n"
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
    
    await state.update_data(pending_company=company)
    company_name = "Бластер" if company == "blaster" else "Культ"
    
    if folder_name:
        # Сценарий 1: Имя папки уже известно (пришли из текстового/голосового запроса)
        await callback.message.edit_text(
            f"<b>Подтвердите создание папки:</b>\n\n"
            f"<b>Компания:</b> {company_name}\n"
            f"<b>Имя папки:</b> {folder_name}",
            reply_markup=get_confirmation_keyboard(),
            parse_mode="HTML"
        )
        await state.set_state(FolderCreation.confirm_creation)
    else:
        # Сценарий 2: Имени папки еще нет (пришли из команды /start)
        await callback.message.edit_text(
            f"Выбрана компания: <b>{company_name}</b>.\n\n"
            f"Введите имя для <b>главной папки</b> ответным сообщением:",
            parse_mode="HTML"
        )
        await state.set_state(FolderCreation.editing_name) # переводим в режим ввода имени
        
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
    
    if action == "yes":
        # 2. Удаляем сообщение с кнопками, чтобы пользователь не нажал их повторно
        await callback.message.delete()
        await state.clear()
        # 3. Запускаем долгий процесс генерации папок и отправки вебхука
        await execute_folder_creation(callback.message, company, folder_name)
        
    elif action == "edit":
        await callback.message.edit_text(
            "✏️ Введите новое название для папки ответным сообщением:",
            parse_mode="Markdown"
        )
        await state.set_state(FolderCreation.editing_name)
        
    elif action == "cancel":
        await callback.message.edit_text("❌ Создание папки отменено.")
        await state.clear()
# --- ОБРАБОТКА ИЗМЕНЕНИЯ ИМЕНИ (Текст) ---
@router.message(FolderCreation.editing_name)
async def process_new_name(message: types.Message, state: FSMContext):
    new_name = message.text.strip()
    user_data = await state.get_data()
    company = user_data.get("pending_company")
    
    await state.update_data(pending_folder_name=new_name)
    company_name = "Бластер" if company == "blaster" else "Культ"
    
    # Повторно показываем карточку с новым именем папки
    await message.answer(
        f"<b>Имя изменено! Подтвердите создание:</b>\n\n"
        f"<b>Компания:</b> {company_name}\n"
        f"<b>Имя папки:</b> {new_name}",
        reply_markup=get_confirmation_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(FolderCreation.confirm_creation)