import os
from dotenv import load_dotenv

load_dotenv()

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

# AmoCRM
AMOCRM_BASE_URL = os.getenv("AMOCRM_BASE_URL", "").rstrip("/")
AMOCRM_API_DOMAIN = os.getenv("AMOCRM_API_DOMAIN")
AMOCRM_ACCESS_TOKEN = os.getenv("AMOCRM_ACCESS_TOKEN")

# Поддомен (fallback, если BASE_URL не задан)
AMOCRM_SUBDOMAIN = os.getenv("AMOCRM_SUBDOMAIN")
AMOCRM_DOMAIN = os.getenv("AMOCRM_DOMAIN", "amocrm.ru")

AMOCRM_SUBDOMAIN_BLASTER = os.getenv("AMOCRM_SUBDOMAIN_BLASTER")
AMOCRM_ACCESS_TOKEN_BLASTER = os.getenv("AMOCRM_ACCESS_TOKEN_BLASTER")
AMOCRM_SUBDOMAIN_CULT = os.getenv("AMOCRM_SUBDOMAIN_CULT")
AMOCRM_ACCESS_TOKEN_CULT = os.getenv("AMOCRM_ACCESS_TOKEN_CULT")

# ID воронок — для проверки, что сделка относится к нужной компании
AMOCRM_PIPELINE_ID_CULT = os.getenv("AMOCRM_PIPELINE_ID_CULT")
AMOCRM_PIPELINE_ID_BLASTER = os.getenv("AMOCRM_PIPELINE_ID_BLASTER") or os.getenv("AMOCRM_PIPELINE_ID_BLUSTER")

# Проверка на наличие критически важных переменных
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN missing in .env file!")