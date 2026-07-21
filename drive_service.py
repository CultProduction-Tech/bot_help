import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
import aiohttp
import logging
import config

async def send_webhook(company: str, folder_name: str, folder_link: str, folder_id: str, deal_id: str | None = None) -> tuple[str, str]:
    """
    Отправляет POST-запрос на сервис компании и возвращает полученный (projectId, project_link).
    """
    webhook_url = config.WEBHOOK_URL_CULT if company == "cult" else config.WEBHOOK_URL_BLASTER
    token = config.TELEGRAM_FOLDER_WEBHOOK_SECRET

    if not webhook_url:
        logging.warning(f"⚠️ Вебхук-URL для компании {company} не настроен. Пропускаю.")
        return "", ""

    payload = {
        "company": company,
        "folder_name": folder_name,
        "folder_id": folder_id,
        "folder_link": folder_link
    }
    if deal_id:
        payload["amo_deal_id"] = deal_id
    
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    logging.info(f"Отправка вебхука на сервис {company} ({webhook_url})...")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload, headers=headers, timeout=10) as response:
                status = response.status
                
                if status in [200, 201]:
                    # Распаковываем JSON ответа
                    response_data = await response.json()
                    project_id = response_data.get("projectId")
                    project_link = response_data.get("projectLink")  # <-- Ожидаем ссылку от системы
                    logging.info(f"✅ Вебхук для {company} успешно доставлен! Получен projectId: {project_id}")
                    return (project_id or "", project_link or "")
                else:
                    error_msg = await response.text()
                    logging.error(f"❌ Сервер {company} вернул ошибку {status}: {error_msg}")
                    return "", ""
                    
    except Exception as e:
        logging.error(f"❌ Ошибка сети при отправке вебхука на {webhook_url}: {e}")
        return "", ""


async def send_cup_webhook(company: str, folder_name: str, folder_link: str, folder_id: str, project_id: str, deal_id: str | None = None) -> str:
    """
    Отправляет POST-запрос в систему CUP, включая полученный ранее project_id.
    Возвращает прямую ссылку на созданный проект в ЦУП.
    """
    webhook_url = config.WEBHOOK_URL_CUP
    token = config.TELEGRAM_CUP_SECRET

    if not webhook_url:
        logging.warning("⚠️ Вебхук-URL для системы CUP не настроен. Пропускаю.")
        return ""

    payload = {
        "company": company,
        "project_name": folder_name,
        "project_id": project_id,
        "google_folder_id": folder_id,
        "google_folder_link": folder_link
    }
    if deal_id:
        payload["amo_deal_id"] = deal_id
    
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    logging.info(f"Отправка вебхука в систему CUP ({webhook_url})...")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload, headers=headers, timeout=10) as response:
                status = response.status
                if status in [200, 201]:
                    logging.info(f"✅ Проект успешно зарегистрирован в CUP! Статус: {status}")
                    response_data = await response.json()
                    return response_data.get("projectLink") or ""  # <-- Ожидаем ссылку от ЦУПа
                else:
                    error_msg = await response.text()
                    logging.error(f"❌ Система CUP вернула ошибку {status}: {error_msg}")
                    return ""
    except Exception as e:
        logging.error(f"❌ Ошибка сети при отправке в CUP: {e}")
        return ""
def get_drive_service(company: str):
    scopes = ['https://www.googleapis.com/auth/drive']
    
    if company == "blaster":
        creds_json_string = os.getenv("CREDENTIALS_BLASTER")
    else:
        creds_json_string = os.getenv("CREDENTIALS_CULT")
        
    if not creds_json_string:
        raise ValueError(f"Переменная окружения для credentials_{company} не настроена!")
        
    creds_info = json.loads(creds_json_string)
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
    return build('drive', 'v3', credentials=creds)

def create_drive_folder(service, name: str, parent_id: str = None):
    file_metadata = {
        'name': name,
        'mimeType': 'application/vnd.google-apps.folder'
    }
    if parent_id:
        file_metadata['parents'] = [parent_id]
        
    # Добавляем supportsAllDrives=True, чтобы API видел папки на общих дисках
    return service.files().create(
        body=file_metadata, 
        fields='id, webViewLink',
        supportsAllDrives=True
    ).execute()

def create_folders_recursive(service, structure, parent_id):
    """
    Принимает структуру в виде словаря или списка и создает ее в Google Drive.
    """
    if isinstance(structure, dict):
        for folder_name, sub_structure in structure.items():
            folder = create_drive_folder(service, folder_name, parent_id)
            folder_id = folder.get('id')
            create_folders_recursive(service, sub_structure, folder_id)
            
    elif isinstance(structure, list):
        for folder_name in structure:
            if isinstance(folder_name, dict):
                create_folders_recursive(service, folder_name, parent_id)
            else:
                create_drive_folder(service, folder_name, parent_id)