import logging
import telegram.ext
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler
from typing import Callable, Coroutine, Any, ClassVar
import asyncio

from .. import RedisConnection
from ..common.config import Config
from ..authentication.auth_account import AuthAccountData
from ..common.api_error import APIError
from ..common.database import Database
from ..authentication.auth_account_factory import AuthAccountFactory
from ..telegram import TelegramBot


logger = logging.getLogger(__name__)


def bot_event_handler(event_type: str) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, Any]]:
    async def handler(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user:
            return

        cur = Database.begin()
        try:
            profile_photos = await user.get_profile_photos(offset=0, limit=1)
            if profile_photos and profile_photos.total_count:
                file_id = profile_photos.photos[0][0].file_id
            else:
                file_id = None

            logger.info(f"TG User {user.id}: {event_type}")
            auth_account = AuthAccountFactory.create_or_update(
                platform="tg", userid=str(user.id), username=user.username, cur=cur,
            )
            await auth_account.update_account_data(
                AuthAccountData(
                    name=" ".join([
                        user.first_name if user.first_name else "",
                        user.last_name if user.last_name else "",
                    ]),
                    profile_pic=file_id
                ),
                cur,
                update=update,
            )

            await auth_account.process_event(event_type, update, cur)
            auth_account.commit_current_state(cur)
            Database.commit()
        except APIError as e:
            Database.rollback()

    return handler


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(context.error)


class Application:
    instance: ClassVar[telegram.ext.Application]

    @staticmethod
    def init(token: str) -> None:
        TelegramBot.init(token)
        Application.instance = ApplicationBuilder().bot(TelegramBot.instance).build()
        Application.instance.add_handler(CommandHandler(command="start", callback=bot_event_handler("start"), block=False))
        Application.instance.add_handler(CommandHandler(command="community", callback=bot_event_handler("community"), block=False))
        Application.instance.add_handler(MessageHandler(filters=None, callback=bot_event_handler("message")))
        Application.instance.add_handler(CallbackQueryHandler(callback=bot_event_handler("callback"), block=False))
        Application.instance.add_error_handler(error_handler)

    @staticmethod
    def run_polling() -> None:
        Application.instance.run_polling()

    @staticmethod
    async def set_webhook(webhook: str) -> None:
        await TelegramBot.instance.set_webhook(
            url=webhook, secret_token=Config.TELEGRAM_BOT_WHOOK_SECRET_TOKEN
        )
        logger.info("Telegram Bot webook set.")

    @staticmethod
    def process_update(update: Update) -> None:
        asyncio.create_task(Application.instance.process_update(update))

    @staticmethod
    async def start_webhook() -> None:
        await Application.instance.initialize()
        await Application.instance.start()

        # Register webhook with preventing multiple calls to TG API
        webhook_sign = RedisConnection.connection.set("TG_WEBHOOK_REGISTERED", "Yes", get=True, ex=3*60)
        if not webhook_sign:
            webhook_url = f"{Config.USER_UI_BASE}/webhooks/telegram/"
            logger.info(f"Registering Telegram Webhook {webhook_url}")
            await Application.set_webhook(webhook_url)

    @staticmethod
    async def stop_webhook() -> None:
        # Deleting webhook with preventing multiple calls to TG API
        webhook_sign = RedisConnection.connection.set("TG_WEBHOOK_REMOVED", "Yes", get=True, ex=3*60)
        if not webhook_sign:
            logger.info(f"Removing Telegram Webhook")
            await TelegramBot.instance.delete_webhook()

        await Application.instance.stop()
        await Application.instance.shutdown()
