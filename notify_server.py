"""
HTTP-relay для исходящих уведомлений из ЦУП.

ЦУП (Timeweb, РФ) не может надёжно достучаться до api.telegram.org напрямую,
поэтому шлёт уведомления сюда, а бот пересылает их в Telegram.

    POST /cup-notify
    Authorization: Bearer <WEBHOOK_SECRET_TELEGRAM_BOT>
    { "text": "...", "parse_mode": "HTML" }
"""

import hmac
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiohttp import web

import config

ALLOWED_PARSE_MODES = {"HTML", "MarkdownV2", "Markdown", None}


def _is_authorized(request: web.Request) -> bool:
    secret = config.WEBHOOK_SECRET_TELEGRAM_BOT
    if not secret:
        logging.error("CUP notify: WEBHOOK_SECRET_TELEGRAM_BOT не настроен в .env")
        return False

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False

    token = auth_header[len("Bearer "):].strip()
    return hmac.compare_digest(token, secret)


def _notify_chat_id() -> int | str | None:
    chat_id = config.TELEGRAM_NOTIFY_CHAT_ID
    if not chat_id:
        return None
    if chat_id.lstrip("-").isdigit():
        return int(chat_id)
    return chat_id


def create_app(bot: Bot) -> web.Application:
    app = web.Application()

    async def cup_notify(request: web.Request) -> web.Response:
        if not _is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        chat_id = _notify_chat_id()
        if not chat_id:
            logging.error("CUP notify: TELEGRAM_NOTIFY_CHAT_ID не настроен в .env")
            return web.json_response({"error": "notify chat is not configured"}, status=500)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)

        if not isinstance(data, dict):
            return web.json_response({"error": "invalid json body"}, status=400)

        text = data.get("text")
        if not text or not isinstance(text, str):
            return web.json_response({"error": "'text' is required"}, status=400)

        parse_mode = data.get("parse_mode", "HTML")
        if parse_mode not in ALLOWED_PARSE_MODES:
            return web.json_response({"error": f"unsupported parse_mode: {parse_mode}"}, status=400)

        try:
            message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )
        except TelegramAPIError as e:
            logging.error(f"CUP notify: Telegram отклонил сообщение: {e}")
            return web.json_response({"error": str(e)}, status=502)
        except Exception as e:
            logging.error(f"CUP notify: непредвиденная ошибка: {e}")
            return web.json_response({"error": str(e)}, status=500)

        logging.info(f"CUP notify: отправлено сообщение message_id={message.message_id}")
        return web.json_response({"ok": True, "message_id": message.message_id})

    app.router.add_post("/cup-notify", cup_notify)
    return app


async def start_notify_server(bot: Bot) -> web.AppRunner:
    app = create_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.HTTP_SERVER_HOST, config.HTTP_SERVER_PORT)
    await site.start()
    logging.info(
        f"CUP notify: HTTP-сервер запущен на {config.HTTP_SERVER_HOST}:{config.HTTP_SERVER_PORT} (POST /cup-notify)"
    )
    return runner
