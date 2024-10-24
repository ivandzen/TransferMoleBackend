import logging
from fastapi import APIRouter
from fastapi.requests import Request
from fastapi.exceptions import HTTPException
from fastapi.responses import PlainTextResponse
from telegram import Update

from .. import Config
from ..telegram import TelegramBot
from ..telegram.application import Application

logger = logging.getLogger(__name__)
router = APIRouter(prefix=f"/telegram", tags=["telegram_webhook"])

@router.post(path="/", response_class=PlainTextResponse)
async def webhook(request: Request) -> str:
    secret_token = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
    if secret_token != Config.TELEGRAM_BOT_WHOOK_SECRET_TOKEN:
        logger.error("Telegram secret token not match")
        raise HTTPException(status_code=403, detail="Invalid secret token")

    update = Update.de_json(await request.json(), TelegramBot.instance)
    if not update:
        logger.error("Failed to  deserialize update object")
        raise HTTPException(status_code=400, detail="Invalid request format")

    Application.process_update(update)
    return "OK"




