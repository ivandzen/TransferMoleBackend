from telegram import Bot
from telegram.request import HTTPXRequest
from typing import ClassVar
import logging

logger = logging.getLogger(__name__)

class TelegramBot:
    instance: ClassVar[Bot]

    @staticmethod
    def init(token: str) -> None:
        trequest = HTTPXRequest(connection_pool_size=256)
        TelegramBot.instance = Bot(token=token, request=trequest)
        logger.info("Telegram Bot initialized.")
