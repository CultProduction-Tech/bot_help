from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

BTN_BY_AMO_ID = "📋 По ID сделки AmoCRM"
BTN_FROM_SCRATCH = "📋 Создать с нуля"
BTN_HELP = "❓ Помощь"
BTN_CANCEL = "❌ Отмена"


def get_main_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=BTN_BY_AMO_ID)
    builder.button(text=BTN_FROM_SCRATCH)
    builder.button(text=BTN_HELP)
    builder.button(text=BTN_CANCEL)
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


def get_company_keyboard(prefix: str = "company") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Бластер", callback_data=f"{prefix}:blaster")
    builder.button(text="Культ", callback_data=f"{prefix}:cult")
    builder.adjust(2)
    return builder.as_markup()


def get_help_text(companies: list[str]) -> str:
    companies_text = ", ".join("Бластер" if c == "blaster" else "Культ" for c in companies)

    return (
        "<b>🤖 Что умеет бот</b>\n\n"
        f"<b>Твои компании:</b> {companies_text}\n\n"
        "<b>📋 Путь 1 — по ID сделки Amo</b>\n"
        "Сделка уже есть в AmoCRM. Отправь ID — бот подтянет название и создаст:\n"
        "• папки на Google Drive\n"
        "• проект в СнупДок\n"
        "• проект в СУП\n\n"
        "<i>Пример: <code>28473651</code> или «сделка 28473651»</i>\n\n"
        "<b>✨ Путь 2 — создать с нуля</b>\n"
        "Отправь название проекта — бот:\n"
        "• создаст сделку в AmoCRM (в нужной воронке)\n"
        "• затем всё по цепочке: AmoCRM → Google Drive → СнупДок → СУП\n\n"
        "<i>Пример: «ПИК ИИ ролики» или «создай папку Альфа Банк культ»</i>\n\n"
        "<b>Также можно:</b>\n"
        "• отправить голосовое сообщение\n"
        "• нажать кнопки внизу для выбора сценария\n"
        "• /start — начать заново\n"
        "• ❌ Отмена — отменить текущее действие\n\n"
        "Перед созданием бот всегда покажет карточку подтверждения."
    )
