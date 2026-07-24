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
AMO_AUTH_HINT = (
    "Токен AmoCRM не принят.\n\n"
    "Перевыпусти <b>долгоживущий ключ</b>:\n"
    "AmoCRM → amoМаркет → твоя интеграция → «Ключи и доступы» → Сгенерировать\n\n"
    "Вставь в .env на сервере:\n"
    "<code>AMOCRM_ACCESS_TOKEN=...</code>\n"
    "(одной строкой, без кавычек)\n\n"
    "Убедись, что интеграция <b>установлена</b> в аккаунте cultteam."
)

_resolved_api_base: str | None = None
_pipeline_status_cache: dict[str, int] = {}


def _is_auth_error(error: str | None) -> bool:
    if not error:
        return False
    e = error.lower()
    return "401" in e or "unauthorized" in e or "токен" in e


def _format_user_amo_error(error: str | None) -> str:
    if _is_auth_error(error):
        return AMO_AUTH_HINT
    return error or "Неизвестная ошибка AmoCRM"


def _get_api_domain_from_token(token: str) -> str | None:
    api_domain = _decode_jwt_payload(token).get("api_domain")
    if not api_domain:
        return None
    if str(api_domain).startswith("http"):
        return str(api_domain).rstrip("/")
    return f"https://{api_domain}"


def _collect_api_bases(token: str) -> list[str]:
    bases: list[str] = []

    def add(url: str | None) -> None:
        if not url:
            return
        normalized = url.strip().rstrip("/")
        if normalized and normalized not in bases:
            bases.append(normalized)

    add(config.AMOCRM_BASE_URL)
    add(_get_api_domain_from_token(token))
    if config.AMOCRM_API_DOMAIN:
        domain = config.AMOCRM_API_DOMAIN.strip().rstrip("/")
        add(domain if domain.startswith("http") else f"https://{domain.lstrip('https://')}")

    return bases


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
        token = config.AMOCRM_ACCESS_TOKEN_BLASTER or config.AMOCRM_ACCESS_TOKEN
    elif company == "cult":
        token = config.AMOCRM_ACCESS_TOKEN_CULT or config.AMOCRM_ACCESS_TOKEN
    else:
        token = config.AMOCRM_ACCESS_TOKEN
    return token.strip() if token else None


def _validate_token_format(token: str | None) -> str | None:
    if not token:
        return "AMOCRM_ACCESS_TOKEN не задан в .env"
    if token.count(".") != 2:
        return "AMOCRM_ACCESS_TOKEN повреждён — должен быть одной строкой (JWT)"
    return None


def _get_expected_pipeline_id(company: str | None) -> str | None:
    if company == "blaster":
        return config.AMOCRM_PIPELINE_ID_BLASTER
    if company == "cult":
        return config.AMOCRM_PIPELINE_ID_CULT
    return None


def _get_configured_status_id(company: str | None) -> int | None:
    raw = None
    if company == "blaster":
        raw = config.AMOCRM_STATUS_ID_BLASTER
    elif company == "cult":
        raw = config.AMOCRM_STATUS_ID_CULT
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
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
                return "; ".join(parts[:3])

        detail = data.get("detail") or data.get("title") or data.get("hint")
        if detail:
            return str(detail)
    return f"ошибка {status}"


def get_deal_link(deal_id: str, company: str | None = None) -> str | None:
    if config.AMOCRM_BASE_URL:
        return f"{config.AMOCRM_BASE_URL.rstrip('/')}/leads/detail/{deal_id}"
    if _resolved_api_base:
        return f"{_resolved_api_base}/leads/detail/{deal_id}"
    return None


async def _resolve_account_api_base(token: str) -> tuple[str | None, str | None]:
    """
    Официальный метод AmoCRM: GET /oauth2/account/subdomain
    https://www.amocrm.ru/developers/content/oauth/account-subdomain-info
    """
    headers = {"Authorization": f"Bearer {token}"}
    oauth_hosts = ["https://www.amocrm.ru", "https://www.kommo.com"]
    last_error = "не удалось определить аккаунт"

    async with aiohttp.ClientSession(timeout=AMO_TIMEOUT) as session:
        for host in oauth_hosts:
            url = f"{host}/oauth2/account/subdomain"
            try:
                async with session.get(url, headers=headers) as response:
                    text = await response.text()
                    if response.status == 401:
                        detail = _parse_amo_error(text, 401)
                        logging.error(f"AmoCRM auth failed on {url}: {detail}")
                        return None, detail
                    if response.status != 200:
                        last_error = _parse_amo_error(text, response.status)
                        logging.warning(f"AmoCRM {url}: {response.status} {text[:200]}")
                        continue

                    data = json.loads(text) if text else {}
                    domain = data.get("domain")
                    if domain:
                        api_base = f"https://{domain}" if not domain.startswith("http") else domain.rstrip("/")
                        logging.info(f"AmoCRM аккаунт: {api_base} (subdomain={data.get('subdomain')})")
                        return api_base, None

                    subdomain = data.get("subdomain")
                    tld = data.get("top_level_domain", "ru")
                    if subdomain:
                        api_base = f"https://{subdomain}.amocrm.{tld}"
                        logging.info(f"AmoCRM аккаунт: {api_base}")
                        return api_base, None
            except Exception as e:
                last_error = str(e)
                logging.error(f"AmoCRM resolve account error {host}: {e}")

    return None, last_error


async def get_amo_api_base(company: str | None = None) -> tuple[str | None, str | None]:
    global _resolved_api_base

    token = _get_amo_token(company)
    fmt_error = _validate_token_format(token)
    if fmt_error:
        return None, fmt_error

    if _resolved_api_base:
        return _resolved_api_base, None

    last_error: str | None = None
    for api_base in _collect_api_bases(token):
        data, _, error = await _amo_get_path(api_base, token, "/api/v4/account")
        if data:
            _resolved_api_base = api_base
            logging.info(f"AmoCRM API base: {api_base}")
            return api_base, None
        last_error = error
        if error and not _is_auth_error(error):
            break
        logging.warning(f"AmoCRM auth failed on {api_base}: {error}")

    api_base, error = await _resolve_account_api_base(token)
    if api_base and api_base not in _collect_api_bases(token):
        data, _, get_error = await _amo_get_path(api_base, token, "/api/v4/account")
        if data:
            _resolved_api_base = api_base
            logging.info(f"AmoCRM API base (oauth resolve): {api_base}")
            return api_base, None
        last_error = get_error or error
    elif error:
        last_error = error

    return None, _format_user_amo_error(last_error)


async def check_amo_on_startup() -> None:
    token = _get_amo_token(None)
    fmt_error = _validate_token_format(token)
    if fmt_error:
        logging.error(f"AmoCRM: {fmt_error}")
        return

    payload = _decode_jwt_payload(token)
    logging.info(
        "AmoCRM token: account_id=%s api_domain=%s len=%s",
        payload.get("account_id"),
        payload.get("api_domain"),
        len(token),
    )

    api_base, error = await get_amo_api_base(None)
    if not api_base:
        logging.error(f"AmoCRM: авторизация не прошла — {error}")
        return

    data, _, get_error = await _amo_get_path(api_base, token, "/api/v4/account")
    if data:
        logging.info(f"AmoCRM OK: {api_base} (account id={data.get('id')}, name={data.get('name')})")
    else:
        logging.error(f"AmoCRM: GET /account failed — {get_error}")


def _extract_statuses_from_pipeline(pipeline: dict) -> list:
    statuses = pipeline.get("_embedded", {}).get("statuses", [])
    if statuses:
        return statuses
    if isinstance(pipeline.get("statuses"), list):
        return pipeline["statuses"]
    return []


async def _amo_get_path(
    api_base: str, token: str, path: str
) -> tuple[Any | None, str | None, str | None]:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{api_base.rstrip('/')}{path}"

    try:
        async with aiohttp.ClientSession(timeout=AMO_TIMEOUT) as session:
            async with session.get(url, headers=headers) as response:
                text = await response.text()
                if response.status == 401:
                    detail = _parse_amo_error(text, 401)
                    logging.error(f"AmoCRM 401 GET {url}: {detail}")
                    return None, None, detail
                if response.status != 200:
                    detail = _parse_amo_error(text, response.status)
                    logging.error(f"AmoCRM {response.status} GET {url}: {detail}\nRAW: {text[:800]}")
                    return None, None, detail
                return json.loads(text) if text else {}, api_base, None
    except Exception as e:
        logging.error(f"AmoCRM GET {url}: {e}")
        return None, None, str(e)


async def _amo_post_path(
    api_base: str, token: str, path: str, payload: Any
) -> tuple[Any | None, str | None, str | None]:
    headers = _amo_headers(token)
    url = f"{api_base.rstrip('/')}{path}"

    try:
        async with aiohttp.ClientSession(timeout=AMO_TIMEOUT) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                text = await response.text()
                if response.status == 401:
                    detail = _parse_amo_error(text, 401)
                    logging.error(f"AmoCRM 401 POST {url}: {detail}")
                    return None, None, detail
                if response.status not in (200, 201):
                    detail = _parse_amo_error(text, response.status)
                    logging.error(f"AmoCRM {response.status} POST {url}: {detail}\nRAW: {text[:800]}")
                    return None, None, detail
                return json.loads(text) if text else {}, api_base, None
    except Exception as e:
        logging.error(f"AmoCRM POST {url}: {e}")
        return None, None, str(e)


async def _amo_get(company: str, path: str) -> tuple[Any | None, str | None, str | None]:
    global _resolved_api_base

    token = _get_amo_token(company)
    if not token:
        return None, None, "AmoCRM токен не настроен"

    fmt_error = _validate_token_format(token)
    if fmt_error:
        return None, None, fmt_error

    bases: list[str] = []
    if _resolved_api_base:
        bases.append(_resolved_api_base)
    for base in _collect_api_bases(token):
        if base not in bases:
            bases.append(base)

    last_error: str | None = None
    for api_base in bases:
        data, _, error = await _amo_get_path(api_base, token, path)
        if not error:
            _resolved_api_base = api_base
            return data, api_base, None
        last_error = error
        if not _is_auth_error(error):
            return None, None, error
        logging.warning(f"AmoCRM 401 GET {api_base}{path}, пробую другой домен...")

    return None, None, _format_user_amo_error(last_error)


async def _amo_post(company: str, path: str, payload: Any) -> tuple[Any | None, str | None, str | None]:
    global _resolved_api_base

    token = _get_amo_token(company)
    if not token:
        return None, None, "AmoCRM токен не настроен"

    fmt_error = _validate_token_format(token)
    if fmt_error:
        return None, None, fmt_error

    bases: list[str] = []
    if _resolved_api_base:
        bases.append(_resolved_api_base)
    for base in _collect_api_bases(token):
        if base not in bases:
            bases.append(base)

    last_error: str | None = None
    for api_base in bases:
        data, _, error = await _amo_post_path(api_base, token, path, payload)
        if not error:
            _resolved_api_base = api_base
            return data, api_base, None
        last_error = error
        if not _is_auth_error(error):
            return None, None, error
        logging.warning(f"AmoCRM 401 POST {api_base}{path}, пробую другой домен...")

    return None, None, _format_user_amo_error(last_error)


async def _get_first_status_id(company: str, pipeline_id: int) -> tuple[int | None, str | None]:
    configured = _get_configured_status_id(company)
    if configured:
        return configured, None

    cache_key = f"{company}:{pipeline_id}"
    if cache_key in _pipeline_status_cache:
        return _pipeline_status_cache[cache_key], None

    data, _, error = await _amo_get(company, f"/api/v4/leads/pipelines/{pipeline_id}")
    statuses: list = []

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
        error = error or list_error

    if not statuses:
        logging.error(f"Воронка {pipeline_id}: этапы не найдены. {error}")
        if _is_auth_error(error):
            return None, AMO_AUTH_HINT
        return None, (
            f"Не удалось получить этапы воронки {pipeline_id}.\n"
            f"{error or 'этапы не найдены'}\n\n"
            "Можно указать ID первого этапа в .env:\n"
            f"<code>AMOCRM_STATUS_ID_{'BLASTER' if company == 'blaster' else 'CULT'}=...</code>"
        )

    logging.info(
        f"Воронка {pipeline_id} ({_company_label(company)}), все этапы: "
        + "; ".join(f"{s.get('id')}={s.get('name')}" for s in statuses)
    )

    # id 142/143 — стандартные across-account статусы "Успешно/Закрыто не реализовано".
    # is_editable=False — системные этапы (в т.ч. "Неразобранное"), в них нельзя
    # создать сделку через обычный POST /leads — AmoCRM вернёт "not a valid choice".
    active_statuses = [
        s for s in statuses
        if s.get("id") not in (142, 143) and s.get("is_editable", True) is not False
    ]
    if not active_statuses:
        logging.warning(
            f"Воронка {pipeline_id}: не нашлось редактируемых этапов, беру любой (может быть ошибка)."
        )
        active_statuses = statuses

    first_status = min(active_statuses, key=lambda s: s.get("sort", 999999))
    status_id = first_status["id"]
    _pipeline_status_cache[cache_key] = status_id
    logging.info(
        f"Воронка {pipeline_id} ({_company_label(company)}): "
        f"этап id={status_id}, name={first_status.get('name')}"
    )
    return status_id, None


async def create_deal(name: str, company: str) -> tuple[str | None, str | None]:
    pipeline_id_raw = _get_expected_pipeline_id(company)
    if not pipeline_id_raw:
        return None, f"Не задан ID воронки для {_company_label(company)}"

    try:
        pipeline_id = int(pipeline_id_raw)
    except ValueError:
        return None, f"Некорректный ID воронки: {pipeline_id_raw}"

    status_id, status_error = await _get_first_status_id(company, pipeline_id)
    if not status_id:
        return None, status_error or (
            f"Не удалось получить этапы воронки {pipeline_id}.\n"
            "Проверь токен AmoCRM или добавь AMOCRM_STATUS_ID_CULT в .env"
        )

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
        f"AmoCRM POST /leads: pipeline={pipeline_id} status={status_id} name={name!r}"
    )

    try:
        data, used_url, error = await _amo_post(company, "/api/v4/leads", [lead_data])
        if error:
            return None, _format_user_amo_error(error)

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
