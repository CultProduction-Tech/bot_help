import os
from dotenv import load_dotenv

load_dotenv()


def _clean_token(raw: str | None) -> str:
    if not raw:
        return ""
    return raw.strip().strip('"').strip("'").replace("\n", "").replace("\r", "")


BOT_TOKEN = os.getenv("BOT_TOKEN")

# Роли пользователей
def parse_ids(env_var_name):
    val = os.getenv(env_var_name, "")
    return {int(x.strip()) for x in val.split(",") if x.strip().isdigit()}

ALLOWED_BLASTER = parse_ids("ALLOWED_IDS_BLASTER")
ALLOWED_CULT = parse_ids("ALLOWED_IDS_CULT")
ALLOWED_BOTH = parse_ids("ALLOWED_IDS_BOTH")

# Google Drive папки
PARENT_FOLDER_BLASTER = os.getenv("PARENT_FOLDER_BLASTER")
PARENT_FOLDER_CULT = os.getenv("PARENT_FOLDER_CULT")

WEBHOOK_URL_CULT = os.getenv("WEBHOOK_URL_CULT")
WEBHOOK_URL_BLASTER = os.getenv("WEBHOOK_URL_BLASTER")
TELEGRAM_FOLDER_WEBHOOK_SECRET = os.getenv("TELEGRAM_FOLDER_WEBHOOK_SECRET")

WEBHOOK_URL_CUP = os.getenv("WEBHOOK_URL_CUP")
TELEGRAM_CUP_SECRET = os.getenv("TELEGRAM_CUP_SECRET")

# Входящие уведомления от ЦУП (relay ЦУП → бот → Telegram).
# Секрет по умолчанию тот же, что используется для исходящих вебхуков в ЦУП,
# но можно задать отдельно через WEBHOOK_SECRET_TELEGRAM_BOT.
WEBHOOK_SECRET_TELEGRAM_BOT = _clean_token(os.getenv("WEBHOOK_SECRET_TELEGRAM_BOT")) or TELEGRAM_CUP_SECRET
TELEGRAM_NOTIFY_CHAT_ID = os.getenv("TELEGRAM_NOTIFY_CHAT_ID", "").strip()
HTTP_SERVER_HOST = os.getenv("HTTP_SERVER_HOST", "0.0.0.0").strip()
HTTP_SERVER_PORT = int(os.getenv("HTTP_SERVER_PORT", "8080") or "8080")

# AmoCRM
AMOCRM_BASE_URL = os.getenv("AMOCRM_BASE_URL", "").strip().rstrip("/")
AMOCRM_API_DOMAIN = os.getenv("AMOCRM_API_DOMAIN", "").strip()
AMOCRM_ACCESS_TOKEN = _clean_token(os.getenv("AMOCRM_ACCESS_TOKEN"))

# Поддомен (fallback, если BASE_URL не задан)
AMOCRM_SUBDOMAIN = os.getenv("AMOCRM_SUBDOMAIN", "").strip()
AMOCRM_DOMAIN = os.getenv("AMOCRM_DOMAIN", "amocrm.ru")

AMOCRM_SUBDOMAIN_BLASTER = os.getenv("AMOCRM_SUBDOMAIN_BLASTER", "").strip()
AMOCRM_ACCESS_TOKEN_BLASTER = _clean_token(os.getenv("AMOCRM_ACCESS_TOKEN_BLASTER"))
AMOCRM_SUBDOMAIN_CULT = os.getenv("AMOCRM_SUBDOMAIN_CULT", "").strip()
AMOCRM_ACCESS_TOKEN_CULT = _clean_token(os.getenv("AMOCRM_ACCESS_TOKEN_CULT"))

# ID воронок — для проверки, что сделка относится к нужной компании
AMOCRM_PIPELINE_ID_CULT = os.getenv("AMOCRM_PIPELINE_ID_CULT", "").strip()
AMOCRM_PIPELINE_ID_BLASTER = (
    os.getenv("AMOCRM_PIPELINE_ID_BLASTER") or os.getenv("AMOCRM_PIPELINE_ID_BLUSTER") or ""
).strip()

# Опционально: ID первого этапа воронки (если API этапов недоступен)
AMOCRM_STATUS_ID_CULT = os.getenv("AMOCRM_STATUS_ID_CULT", "").strip()
AMOCRM_STATUS_ID_BLASTER = os.getenv("AMOCRM_STATUS_ID_BLASTER", "").strip()

# Ответственный за сделку при создании (Amo user id)
AMOCRM_RESPONSIBLE_USER_ID_CULT = os.getenv("AMOCRM_RESPONSIBLE_USER_ID_CULT", "").strip()
AMOCRM_RESPONSIBLE_USER_ID_BLASTER = os.getenv("AMOCRM_RESPONSIBLE_USER_ID_BLASTER", "").strip()

# Кастомное поле «Папка проекта» в сделке AmoCRM (field id)
AMOCRM_FOLDER_FIELD_ID_CULT = os.getenv("AMOCRM_FOLDER_FIELD_ID_CULT", "").strip()
AMOCRM_FOLDER_FIELD_ID_BLASTER = os.getenv("AMOCRM_FOLDER_FIELD_ID_BLASTER", "").strip()

# Проверка на наличие критически важных переменных
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN missing in .env file!")