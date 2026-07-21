import logging
import re

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
