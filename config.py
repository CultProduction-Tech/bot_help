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

# Проверка на наличие критически важных переменных
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN missing in .env file!")