from telegram import Bot, Update
from telegram.request import HTTPXRequest
from telegram.ext import ApplicationBuilder, ChatMemberHandler, ContextTypes, MessageHandler
import logging
from typing import Set
import asyncio

from ...lib.common.config import Config
from ...lib.common.database import Database
from ...lib import init_transfer_mole

logger = logging.getLogger(__name__)
SECRET_PHRASE = "moleyouneedislove"
WHITELISTED_CHATS: Set[int] = set()

metrics_query = """
SELECT '1-tg-users' AS metric_type, COUNT(*) - 262 FROM public.auth_account WHERE platform='tg'
    UNION
SELECT '2-users-registered' AS metric_type, COUNT(*) - 243 FROM public.auth_account
    INNER JOIN public.creator c on c.creator_id = auth_account.creator_id
                                          WHERE platform='tg'
    UNION
SELECT '3-wallets-attached' AS metric_type, COUNT(DISTINCT c.creator_id) - 161 FROM public.auth_account
    INNER JOIN public.creator c on c.creator_id = auth_account.creator_id
    INNER JOIN public.payout_channel pc on auth_account.creator_id = pc.creator_id
WHERE platform='tg'
ORDER BY metric_type;
"""

init_transfer_mole()
trequest = HTTPXRequest(connection_pool_size=256)
bot = Bot(token=Config.TELEGRAM_REPORTER_BOT_TOKEN, request=trequest)


async def broadcast_metrics() -> None:
    cur = Database.begin()
    cur.execute(metrics_query)

    message = ""
    for entry in cur:
        message += f"{entry[0]} : {entry[1]}\n"

    for chat_id in WHITELISTED_CHATS:
        await bot.send_message(chat_id=chat_id, text=message)


async def monitoring_task() -> None:
    while True:
        await broadcast_metrics()
        await asyncio.sleep(3600)


async def bot_added_to_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Check if the bot was added to the group
    new_chat_member = update.my_chat_member.new_chat_member
    if new_chat_member.user.id == context.bot.id and new_chat_member.status == 'member':
        chat_id = update.my_chat_member.chat.id
        await context.bot.send_message(chat_id, "Send secret phrase.")


async def message_handler(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or update.message.text != SECRET_PHRASE:
        return

    if update.message.chat_id in WHITELISTED_CHATS:
        return

    WHITELISTED_CHATS.add(update.message.chat_id)
    if len(WHITELISTED_CHATS) == 1:
        asyncio.create_task(monitoring_task())


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(context.error)


app = ApplicationBuilder().bot(bot).build()
app.add_handler(ChatMemberHandler(bot_added_to_chat, ChatMemberHandler.MY_CHAT_MEMBER))
app.add_handler(MessageHandler(filters=None, callback=message_handler))
app.add_error_handler(error_handler)
app.run_polling()
