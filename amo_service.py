import asyncio
import json
import logging
import re
from typing import Any

import aiohttp

import config

DEAL_ID_PATTERN = re.compile(
    r"(?:сделк[аиуё]|deal|lead|лид|id|amo|амо|#)[^\d]*(\d+)|"
    r"(?:создай|сделай|папк[ау])[^\d]*(\d+)",
    re.IGNORECASE,
)


def extract_deal_id(text: str) -> str | None:
    """Извлекает ID сделки AmoCRM из текста пользователя."""
    text = text.strip()
    if not text:
        return None

    if re.fullmatch(r"\d+", text):
        return text

    match = DEAL_ID_PATTERN.search(text)
    if match:
        return match.group(1) or match.group(2)

    return None


def _get_amo_base_url(company: str | None = None) -> str | None:
    if config.AMOCRM_API_DOMAIN:
        domain = config.AMOCRM_API_DOMAIN.strip().rstrip("/")
        if domain.startswith("http"):
            return domain
        return f"https://{domain}"

    if company == "blaster":
        subdomain = config.AMOCRM_SUBDOMAIN_BLASTER or config.AMOCRM_SUBDOMAIN
        if subdomain:
            return f"https://{subdomain}.{config.AMOCRM_DOMAIN}".rstrip("/")
        return config.AMOCRM_BASE_URL or None

    if company == "cult":
        subdomain = config.AMOCRM_SUBDOMAIN_CULT or config.AMOCRM_SUBDOMAIN
        if subdomain:
            return f"https://{subdomain}.{config.AMOCRM_DOMAIN}".rstrip("/")
        return config.AMOCRM_BASE_URL or None

    if config.AMOCRM_BASE_URL:
        return config.AMOCRM_BASE_URL

    if config.AMOCRM_SUBDOMAIN:
        return f"https://{config.AMOCRM_SUBDOMAIN}.{config.AMOCRM_DOMAIN}".rstrip("/")

    return None


def _get_amo_token(company: str | None = None) -> str | None:
    if company == "blaster":
        return config.AMOCRM_ACCESS_TOKEN_BLASTER or config.AMOCRM_ACCESS_TOKEN
    if company == "cult":
        return config.AMOCRM_ACCESS_TOKEN_CULT or config.AMOCRM_ACCESS_TOKEN
    return config.AMOCRM_ACCESS_TOKEN


def _get_expected_pipeline_id(company: str | None) -> str | None:
    if company == "blaster":
        return config.AMOCRM_PIPELINE_ID_BLASTER
    if company == "cult":
        return config.AMOCRM_PIPELINE_ID_CULT
    return None


def _company_label(company: str) -> str:
    return "Бластер" if company == "blaster" else "Культ"


def _amo_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _parse_created_leads(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict) and item.get("id")]

    if isinstance(data, dict):
        embedded = data.get("_embedded", {})
        leads = embedded.get("leads", [])
        if isinstance(leads, list):
            return [item for item in leads if isinstance(item, dict) and item.get("id")]

    return []


def get_deal_link(deal_id: str, company: str | None = None) -> str | None:
    base_url = config.AMOCRM_BASE_URL or _get_amo_base_url(company)
    if not base_url:
        return None
    return f"{base_url.rstrip('/')}/leads/detail/{deal_id}"


_pipeline_status_cache: dict[str, int] = {}


async def _get_first_status_id(company: str, pipeline_id: int) -> int | None:
    cache_key = f"{company}:{pipeline_id}"
    if cache_key in _pipeline_status_cache:
        return _pipeline_status_cache[cache_key]

    base_url = _get_amo_base_url(company)
    token = _get_amo_token(company)
    if not base_url or not token:
        return None

    headers = _amo_headers(token)

    try:
        async with aiohttp.ClientSession() as session:
            statuses: list = []
            url = f"{base_url}/api/v4/leads/pipelines/{pipeline_id}"
            async with session.get(url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    statuses = data.get("_embedded", {}).get("statuses", [])
                    if not statuses and isinstance(data.get("statuses"), list):
                        statuses = data["statuses"]
                else:
                    logging.warning(
                        f"Не удалось получить воронку {pipeline_id} напрямую: {response.status}"
                    )
                    list_url = f"{base_url}/api/v4/leads/pipelines"
                    async with session.get(list_url, headers=headers, timeout=15) as list_response:
                        if list_response.status != 200:
                            error_text = await list_response.text()
                            logging.error(
                                f"Не удалось получить список воронок: "
                                f"{list_response.status} {error_text}"
                            )
                            return None
                        data = await list_response.json()
                        pipelines = data.get("_embedded", {}).get("pipelines", [])
                        for pipeline in pipelines:
                            if pipeline.get("id") == pipeline_id:
                                statuses = pipeline.get("_embedded", {}).get("statuses", [])
                                break

            if not statuses:
                logging.error(f"У воронки {pipeline_id} не найдены этапы")
                return None

            first_status = min(statuses, key=lambda s: s.get("sort", 0))
            status_id = first_status["id"]
            _pipeline_status_cache[cache_key] = status_id
            return status_id
    except Exception as e:
        logging.error(f"Ошибка получения этапов воронки {pipeline_id}: {e}")
        return None


async def create_deal(name: str, company: str) -> tuple[str | None, str | None]:
    """Создаёт сделку в AmoCRM. Возвращает (deal_id, error_message)."""
    base_url = _get_amo_base_url(company)
    token = _get_amo_token(company)
    pipeline_id_raw = _get_expected_pipeline_id(company)

    if not base_url or not token:
        return None, "AmoCRM не настроен: проверь AMOCRM_BASE_URL и AMOCRM_ACCESS_TOKEN"
    if not pipeline_id_raw:
        return None, f"Не задан ID воронки для {_company_label(company)}"

    try:
        pipeline_id = int(pipeline_id_raw)
    except ValueError:
        return None, f"Некорректный ID воронки: {pipeline_id_raw}"

    status_id = await _get_first_status_id(company, pipeline_id)

    lead_data: dict[str, Any] = {
        "name": name,
        "pipeline_id": pipeline_id,
        "created_by": 0,
    }
    if status_id:
        lead_data["status_id"] = status_id

    url = f"{base_url}/api/v4/leads"
    headers = _amo_headers(token)
    payload = [lead_data]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=20) as response:
                response_text = await response.text()

                if response.status not in (200, 201):
                    logging.error(
                        f"AmoCRM не создал сделку: {response.status} {response_text}"
                    )
                    return None, f"AmoCRM вернул ошибку {response.status}"

                try:
                    data = json.loads(response_text) if response_text else {}
                except json.JSONDecodeError:
                    logging.error(f"AmoCRM: не удалось разобрать ответ: {response_text}")
                    return None, "AmoCRM вернул некорректный ответ"

                leads = _parse_created_leads(data)
                if not leads:
                    logging.error(f"AmoCRM: пустой ответ после создания: {data}")
                    return None, "AmoCRM не вернул ID созданной сделки"

                deal_id = str(leads[0]["id"])
                logging.info(
                    f"Создана сделка #{deal_id} «{name}» в воронке {_company_label(company)}"
                )
                return deal_id, None
    except asyncio.TimeoutError:
        logging.error("Таймаут при создании сделки в AmoCRM")
        return None, "Превышено время ожидания ответа AmoCRM"
    except Exception as e:
        logging.error(f"Ошибка создания сделки в AmoCRM: {e}")
        return None, "Ошибка сети при обращении к AmoCRM"


async def get_deal_name(deal_id: str, company: str | None = None) -> str | None:
    """Получает название сделки из AmoCRM по её ID."""
    base_url = _get_amo_base_url(company)
    token = _get_amo_token(company)

    if not base_url or not token:
        logging.error(
            "AmoCRM не настроен: укажите AMOCRM_BASE_URL и AMOCRM_ACCESS_TOKEN в .env"
        )
        return None

    url = f"{base_url}/api/v4/leads/{deal_id}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as response:
                if response.status == 404:
                    logging.warning(f"Сделка {deal_id} не найдена в AmoCRM ({base_url})")
                    return None
                if response.status != 200:
                    error_text = await response.text()
                    logging.error(
                        f"AmoCRM вернул {response.status} для сделки {deal_id}: {error_text}"
                    )
                    return None

                data = await response.json()
                name = data.get("name")
                if not name:
                    logging.warning(f"Сделка {deal_id} найдена, но название пустое")
                    return None

                expected_pipeline = _get_expected_pipeline_id(company)
                if expected_pipeline:
                    deal_pipeline = str(data.get("pipeline_id", ""))
                    if deal_pipeline and deal_pipeline != str(expected_pipeline):
                        logging.warning(
                            f"Сделка {deal_id} из воронки {deal_pipeline}, "
                            f"ожидалась {expected_pipeline} для {_company_label(company)}"
                        )
                        return None

                return name.strip()
    except Exception as e:
        logging.error(f"Ошибка запроса к AmoCRM для сделки {deal_id}: {e}")
        return None
