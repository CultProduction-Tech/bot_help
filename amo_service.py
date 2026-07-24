import asyncio
import base64
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

AMO_TIMEOUT = aiohttp.ClientTimeout(total=20, connect=10)


def extract_deal_id(text: str) -> str | None:
    text = text.strip()
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        return text
    match = DEAL_ID_PATTERN.search(text)
    if match:
        return match.group(1) or match.group(2)
    return None


def _decode_jwt_payload(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _get_api_domain_from_token(token: str | None) -> str | None:
    if not token:
        return None
    return _decode_jwt_payload(token).get("api_domain")


def _get_user_id_from_token(token: str | None) -> int | None:
    if not token:
        return None
    sub = _decode_jwt_payload(token).get("sub")
    try:
        return int(sub) if sub else None
    except (TypeError, ValueError):
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


def _get_amo_api_url_candidates(company: str | None = None) -> list[str]:
    """Список доменов для API — пробуем по порядку (BASE_URL первым)."""
    candidates: list[str] = []
    seen: set[str] = set()

    def add(url: str | None):
        if not url:
            return
        normalized = url.strip().rstrip("/")
        if not normalized.startswith("http"):
            normalized = f"https://{normalized}"
        if normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)

    if config.AMOCRM_API_DOMAIN:
        add(config.AMOCRM_API_DOMAIN)

    add(config.AMOCRM_BASE_URL)

    token = _get_amo_token(company)
    api_domain = _get_api_domain_from_token(token)
    if api_domain:
        add(f"https://{api_domain}")

    if company == "blaster":
        subdomain = config.AMOCRM_SUBDOMAIN_BLASTER or config.AMOCRM_SUBDOMAIN
    elif company == "cult":
        subdomain = config.AMOCRM_SUBDOMAIN_CULT or config.AMOCRM_SUBDOMAIN
    else:
        subdomain = config.AMOCRM_SUBDOMAIN

    if subdomain:
        add(f"https://{subdomain}.{config.AMOCRM_DOMAIN}")

    return candidates


def _amo_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _parse_created_leads(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict) and item.get("id")]
    if isinstance(data, dict):
        leads = data.get("_embedded", {}).get("leads", [])
        if isinstance(leads, list):
            return [item for item in leads if isinstance(item, dict) and item.get("id")]
    return []


def _parse_amo_error(response_text: str, status: int) -> str:
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        return f"AmoCRM вернул ошибку {status}"

    if isinstance(data, dict):
        detail = data.get("detail") or data.get("title")
        if detail:
            return f"AmoCRM: {detail}"
        validation_errors = data.get("validation-errors")
        if validation_errors:
            parts = []
            for block in validation_errors:
                for err in block.get("errors", []):
                    path = err.get("path", "")
                    msg = err.get("detail") or err.get("code", "")
                    if path or msg:
                        parts.append(f"{path}: {msg}".strip(": "))
            if parts:
                return "AmoCRM: " + "; ".join(parts[:3])
    return f"AmoCRM вернул ошибку {status}"


def get_deal_link(deal_id: str, company: str | None = None) -> str | None:
    base_url = config.AMOCRM_BASE_URL
    if not base_url:
        token = _get_amo_token(company)
        payload = _decode_jwt_payload(token or "")
        base_domain = payload.get("base_domain", config.AMOCRM_DOMAIN)
        if config.AMOCRM_SUBDOMAIN:
            base_url = f"https://{config.AMOCRM_SUBDOMAIN}.{base_domain}"
    if not base_url:
        return None
    return f"{base_url.rstrip('/')}/leads/detail/{deal_id}"


_pipeline_status_cache: dict[str, int] = {}


def _extract_statuses_from_pipeline(pipeline: dict) -> list:
    statuses = pipeline.get("_embedded", {}).get("statuses", [])
    if statuses:
        return statuses
    if isinstance(pipeline.get("statuses"), list):
        return pipeline["statuses"]
    return []


async def _amo_get(company: str, path: str) -> tuple[Any | None, str | None, str | None]:
    """GET запрос к AmoCRM с fallback по доменам. Возвращает (data, used_base_url, error)."""
    token = _get_amo_token(company)
    if not token:
        return None, None, "AmoCRM токен не настроен"

    candidates = _get_amo_api_url_candidates(company)
    if not candidates:
        return None, None, "AmoCRM URL не настроен"

    headers = {"Authorization": f"Bearer {token}"}
    last_error = "нет доступных доменов"

    async with aiohttp.ClientSession(timeout=AMO_TIMEOUT) as session:
        for base_url in candidates:
            url = f"{base_url}{path}"
            try:
                async with session.get(url, headers=headers) as response:
                    text = await response.text()
                    if response.status == 401:
                        logging.warning(f"AmoCRM 401 на {base_url}{path}")
                        last_error = "401 Unauthorized"
                        continue
                    if response.status != 200:
                        last_error = f"{response.status}: {text[:300]}"
                        logging.error(f"AmoCRM GET {path} на {base_url}: {last_error}")
                        continue
                    data = json.loads(text) if text else {}
                    logging.info(f"AmoCRM GET OK: {base_url}{path}")
                    return data, base_url, None
            except Exception as e:
                last_error = str(e)
                logging.error(f"AmoCRM GET ошибка {base_url}{path}: {e}")

    return None, None, last_error


async def _amo_post(company: str, path: str, payload: Any) -> tuple[Any | None, str | None, str | None]:
    token = _get_amo_token(company)
    if not token:
        return None, None, "AmoCRM токен не настроен"

    candidates = _get_amo_api_url_candidates(company)
    headers = _amo_headers(token)
    last_error = "нет доступных доменов"

    async with aiohttp.ClientSession(timeout=AMO_TIMEOUT) as session:
        for base_url in candidates:
            url = f"{base_url}{path}"
            try:
                async with session.post(url, json=payload, headers=headers) as response:
                    text = await response.text()
                    if response.status == 401:
                        logging.warning(f"AmoCRM 401 POST на {base_url}{path}")
                        last_error = "401 Unauthorized"
                        continue
                    if response.status not in (200, 201):
                        last_error = _parse_amo_error(text, response.status)
                        logging.error(f"AmoCRM POST {path} на {base_url}: {response.status} {text}")
                        continue
                    data = json.loads(text) if text else {}
                    logging.info(f"AmoCRM POST OK: {base_url}{path}")
                    return data, base_url, None
            except Exception as e:
                last_error = str(e)
                logging.error(f"AmoCRM POST ошибка {base_url}{path}: {e}")

    return None, None, last_error


async def _get_first_status_id(company: str, pipeline_id: int) -> int | None:
    cache_key = f"{company}:{pipeline_id}"
    if cache_key in _pipeline_status_cache:
        return _pipeline_status_cache[cache_key]

    data, _, error = await _amo_get(company, f"/api/v4/leads/pipelines/{pipeline_id}")
    statuses: list = []
    list_error = None

    if data:
        statuses = _extract_statuses_from_pipeline(data)

    if not statuses:
        list_data, _, list_error = await _amo_get(company, "/api/v4/leads/pipelines")
        if list_data:
            pipelines = list_data.get("_embedded", {}).get("pipelines", [])
            for pipeline in pipelines:
                if pipeline.get("id") == pipeline_id:
                    statuses = _extract_statuses_from_pipeline(pipeline)
                    break

    if not statuses:
        logging.error(f"Воронка {pipeline_id}: этапы не найдены. Ошибка: {error or list_error}")
        return None

    active_statuses = [s for s in statuses if s.get("type") not in (142, 143)]
    if not active_statuses:
        active_statuses = statuses

    first_status = min(active_statuses, key=lambda s: s.get("sort", 999999))
    status_id = first_status["id"]
    _pipeline_status_cache[cache_key] = status_id
    logging.info(
        f"Воронка {pipeline_id} ({_company_label(company)}): "
        f"этап id={status_id}, name={first_status.get('name')}"
    )
    return status_id


async def create_deal(name: str, company: str) -> tuple[str | None, str | None]:
    pipeline_id_raw = _get_expected_pipeline_id(company)
    if not pipeline_id_raw:
        return None, f"Не задан ID воронки для {_company_label(company)}"

    try:
        pipeline_id = int(pipeline_id_raw)
    except ValueError:
        return None, f"Некорректный ID воронки: {pipeline_id_raw}"

    status_id = await _get_first_status_id(company, pipeline_id)
    if not status_id:
        return None, f"Не удалось получить этапы воронки {pipeline_id}. Проверь токен AmoCRM."

    token = _get_amo_token(company)
    responsible_user_id = _get_user_id_from_token(token)

    lead_data: dict[str, Any] = {
        "name": name,
        "pipeline_id": pipeline_id,
        "status_id": status_id,
    }
    if responsible_user_id:
        lead_data["responsible_user_id"] = responsible_user_id

    logging.info(
        f"AmoCRM создаю сделку: pipeline={pipeline_id} status={status_id} name={name!r}"
    )

    try:
        data, used_url, error = await _amo_post(company, "/api/v4/leads", [lead_data])
        if error:
            return None, error

        leads = _parse_created_leads(data)
        if not leads:
            logging.error(f"AmoCRM: пустой ответ после создания: {data}")
            return None, "AmoCRM не вернул ID созданной сделки"

        deal_id = str(leads[0]["id"])
        logging.info(f"Создана сделка #{deal_id} через {used_url}")
        return deal_id, None
    except asyncio.TimeoutError:
        return None, "Превышено время ожидания AmoCRM (20 сек)"
    except Exception as e:
        logging.error(f"Ошибка создания сделки: {e}")
        return None, f"Ошибка AmoCRM: {e}"


async def get_deal_name(deal_id: str, company: str | None = None) -> str | None:
    data, _, error = await _amo_get(company, f"/api/v4/leads/{deal_id}")
    if not data:
        logging.error(f"Сделка {deal_id} не найдена: {error}")
        return None

    name = data.get("name")
    if not name:
        return None

    expected_pipeline = _get_expected_pipeline_id(company)
    if expected_pipeline:
        deal_pipeline = str(data.get("pipeline_id", ""))
        if deal_pipeline and deal_pipeline != str(expected_pipeline):
            logging.warning(
                f"Сделка {deal_id} из воронки {deal_pipeline}, ожидалась {expected_pipeline}"
            )
            return None

    return name.strip()
