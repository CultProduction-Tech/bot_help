import json
import logging
import os
from pathlib import Path

import aiohttp
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import config

BASE_DIR = Path(__file__).resolve().parent
CULT_TEMPLATES_BASE = BASE_DIR / "templates" / "cult"

MIME_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".psd": "image/vnd.adobe.photoshop",
}

# (folder_path on Drive, local templates subdir, list of source -> target filename)
CULT_SEED_GROUPS = [
    (
        ["3 - Documents", "Money", "CE"],
        "ce",
        [
            ("ce_cult_project_name.xlsx", lambda pn: f"CE CULT {pn}.xlsx"),
            ("ai_template_ce_cult.xlsx", lambda _pn: "AI_TEMPLATE_ CE CULT.xlsx"),
            ("cult_template_production_approach.pptx", lambda _pn: "CULT Template Production Approach.pptx"),
        ],
    ),
    (
        ["1 - Presale"],
        "presale",
        [("Адекватность.docx", lambda _pn: "Адекватность.docx")],
    ),
    (
        ["1 - Presale", "Creative"],
        "presale/creative",
        [
            ("CULT CREATIVE TEMPLATE 2025 (1).pptx", lambda _pn: "CULT CREATIVE TEMPLATE 2025 (1).pptx"),
            ("CULT CREATIVE TEMPLATE 2025.pptx", lambda _pn: "CULT CREATIVE TEMPLATE 2025.pptx"),
        ],
    ),
    (
        ["1 - Presale", "Brief"],
        "presale/brief",
        [
            ("Creative + production brief CULT.docx", lambda _pn: "Creative + production brief CULT.docx"),
            ("Creative brief CULT short version.docx", lambda _pn: "Creative brief CULT short version.docx"),
            ("Creative brief CULT.docx", lambda _pn: "Creative brief CULT.docx"),
            ("Production brief CULT.docx", lambda _pn: "Production brief CULT.docx"),
        ],
    ),
    (
        ["2 - Project", "00 - Brief"],
        "project/00-brief",
        [("CULT BRIEF TEMPLATE.pptx", lambda _pn: "CULT BRIEF TEMPLATE.pptx")],
    ),
    (
        ["2 - Project", "01 - Script"],
        "project/01-script",
        [("STORYBOARD_TEMPLATE_CULT_DDMMYY.docx", lambda _pn: "STORYBOARD_TEMPLATE_CULT_DDMMYY.docx")],
    ),
    (
        ["2 - Project", "03 - Casting"],
        "project/03-casting",
        [("CASTING Template.pptx", lambda _pn: "CASTING Template.pptx")],
    ),
    (
        ["2 - Project", "04 - Wardrobe"],
        "project/04-wardrobe",
        [("WARDROBE_TEMPLATE_CULT_ДДММГГ.pptx", lambda _pn: "WARDROBE_TEMPLATE_CULT_ДДММГГ.pptx")],
    ),
    (
        ["2 - Project", "05 - Locations"],
        "project/05-locations",
        [
            ("Чек лист по локации.docx", lambda _pn: "Чек лист по локации.docx"),
            ("Locations_template.pptx", lambda _pn: "Locations_template.pptx"),
        ],
    ),
    (
        ["2 - Project", "06 - Props"],
        "project/06-props",
        [("Props_template.pptx", lambda _pn: "Props_template.pptx")],
    ),
    (
        ["2 - Project", "07 - Edit", "TT", "ЭФИРНАЯ РАМКА"],
        "project/07-edit/tt/efirnaya-ramka",
        None,
    ),
    (
        ["2 - Project", "12 - pre-PPM-PPM"],
        "project/12-ppm",
        [
            ("CULT_PPM_Book_TEMPLATE.pptx", lambda _pn: "CULT_PPM_Book_TEMPLATE.pptx"),
            ("PPM Report CULT.docx", lambda _pn: "PPM Report CULT.docx"),
        ],
    ),
    (
        ["2 - Project", "13 - Timing"],
        "project/13-timing",
        [("TIMING_2026_TEMPLATE_CULT.xlsx", lambda _pn: "TIMING_2026_TEMPLATE_CULT.xlsx")],
    ),
    (
        ["2 - Project", "15 - Administration"],
        "project/15-administration",
        [
            ("Шаблон_Чек-лист.xlsx", lambda _pn: "Шаблон_Чек-лист.xlsx"),
            ("CREW_LIST_TEMPLATE.xlsx", lambda _pn: "CREW_LIST_TEMPLATE.xlsx"),
        ],
    ),
    (
        ["2 - Project", "16 - PR"],
        "project/16-pr",
        [("CREDITS_PROJECT_CULT.docx", lambda _pn: "CREDITS_PROJECT_CULT.docx")],
    ),
    (
        ["2 - Project", "17 - Safety"],
        "project/17-safety",
        [
            ("ИНСТРУКТАЖ ПО ТБ ДЛЯ СЪЕМОЧНОЙ ГРУППЫ CULT.pdf", lambda _pn: "ИНСТРУКТАЖ ПО ТБ ДЛЯ СЪЕМОЧНОЙ ГРУППЫ CULT.pdf"),
            ("Форма подтверждения прослушивания инструктажа по технике безопасности.docx", lambda _pn: "Форма подтверждения прослушивания инструктажа по технике безопасности.docx"),
        ],
    ),
]

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
        "google_folder_link": folder_link,
        "amo_deal_id": int(deal_id) if deal_id and deal_id.isdigit() else deal_id,
    }
    
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


def find_folder_by_path(service, root_id: str, path_parts: list[str]) -> str | None:
    current_id = root_id
    for part in path_parts:
        safe_name = part.replace("\\", "\\\\").replace("'", "\\'")
        query = (
            f"'{current_id}' in parents and "
            f"mimeType='application/vnd.google-apps.folder' and "
            f"name='{safe_name}' and trashed=false"
        )
        response = service.files().list(
            q=query,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            pageSize=1,
        ).execute()
        files = response.get("files", [])
        if not files:
            logging.error(f"Папка не найдена в Drive: {' / '.join(path_parts)} (на шаге {part!r})")
            return None
        current_id = files[0]["id"]
    return current_id


def upload_local_file(service, local_path: Path, drive_filename: str, parent_id: str) -> dict:
    ext = local_path.suffix.lower()
    media = MediaFileUpload(
        str(local_path),
        mimetype=MIME_TYPES.get(ext, "application/octet-stream"),
        resumable=True,
    )
    file_metadata = {"name": drive_filename, "parents": [parent_id]}
    return service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink",
        supportsAllDrives=True,
    ).execute()


def seed_cult_templates(service, main_folder_id: str, project_name: str) -> None:
    for folder_path, templates_subdir, files in CULT_SEED_GROUPS:
        folder_id = find_folder_by_path(service, main_folder_id, folder_path)
        if not folder_id:
            logging.error(f"Не удалось найти папку {' / '.join(folder_path)} для шаблонов Cult")
            continue

        templates_dir = CULT_TEMPLATES_BASE / templates_subdir
        if not templates_dir.is_dir():
            logging.error(f"Каталог шаблонов Cult не найден: {templates_dir}")
            continue

        if files is None:
            file_entries = [
                (path.name, lambda _pn, name=path.name: name)
                for path in sorted(templates_dir.iterdir())
                if path.is_file()
            ]
        else:
            file_entries = files

        for source_name, target_fn in file_entries:
            local_path = templates_dir / source_name
            if not local_path.exists():
                logging.error(f"Шаблон Cult не найден на диске: {local_path}")
                continue

            drive_filename = target_fn(project_name)
            try:
                uploaded = upload_local_file(service, local_path, drive_filename, folder_id)
                logging.info(
                    f"Загружен шаблон Cult в {' / '.join(folder_path)}: "
                    f"{drive_filename} (id={uploaded.get('id')})"
                )
            except Exception as e:
                logging.error(f"Не удалось загрузить шаблон {local_path.name}: {e}")