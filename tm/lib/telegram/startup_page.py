from attr import dataclass
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, User
from telegram.constants import ParseMode
import logging
import asyncio

from ..common.api_error import APIError
from ..common.config import Config
from .inline_form import BaseFormPage
from ..creator import Creator
from ..authentication.auth_account import AuthAccount
from .common import dashboard_message

logger = logging.getLogger(__name__)
CAPTION="""
👋 *Welcome to TransferMole*

Sign up and start receiving crypto & card payments with your Telegram username\.\n
🔥As an early user, you are also eligible to participate in our $100,000 incentive program\. Click Play\-to\-earn for details\.
"""

class Callback:
    DASHBOARD = "startup.dashboard"
    PAYMENT_LINK = "startup.my_payment_link"
    WHACK_A_MOLE = "startup.whack_a_mole"
    NO_USERNAME = "startup.no_username"

@dataclass
class StartupPage(BaseFormPage):
    async def picture(self, _user: User, creator: Creator | None) -> str:
        return "https://app.transfermole.com/pictures/tg-header-1.jpg"

    async def caption(self, _user: User, creator: Creator | None) -> str | None:
        return CAPTION

    async def markup(self, user: User, creator: Creator | None) -> InlineKeyboardMarkup | None:
        first_button_text = "🔥 Signup and earn extra" if not creator else "Open App"
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(text=first_button_text, callback_data=Callback.DASHBOARD)],
            [InlineKeyboardButton(text="Make Payment", url=f"{Config.USER_UI_BASE}")],
            [InlineKeyboardButton(text="Receive payments", callback_data=Callback.PAYMENT_LINK)],
            [InlineKeyboardButton(text="🔥 Play-to-earn", callback_data=Callback.WHACK_A_MOLE)],
        ])

    async def process_callback_query(
            self,
            query: str,
            message: Message,
            user: User,
            creator: Creator | None,
            auth_account: AuthAccount,
    ) -> str | None:
        match query:
            case Callback.DASHBOARD:
                await dashboard_message(creator, message, auth_account)

            case Callback.PAYMENT_LINK:
                if not creator:
                    msg = await message.reply_text(
                        text="You need to sign up before being able to accept payments with your Telegram username."
                    )

                    await asyncio.sleep(10)
                    await msg.delete()
                    return None

                if not user.username:
                    await message.reply_text(
                        text="Please, setup username for your account. Until then, you can not receive payments.",
                        protect_content=True,
                    )
                else:
                    await message.reply_text(
                        text=f"Forward your payment link to the sender\n 👇👇👇",
                        protect_content=True,
                    )

                    creator_id_str = str(creator.creator_id).replace('-', '\-')
                    payment_link = f"{Config.USER_UI_BASE}/pay/{creator_id_str}"
                    payment_link_text = payment_link.replace('.', '\.')
                    await message.reply_text(
                        text=(
                            f'Pay my telegram username [@{user.username}](tg://user?id={user.id})\n'
                            f'[{payment_link_text}]({payment_link})'
                        ),
                        parse_mode=ParseMode.MARKDOWN_V2,
                    )

            case Callback.WHACK_A_MOLE:
                return "whack_a_mole"

            case Callback.NO_USERNAME:
                await message.delete()
                await message.reply_text(
                    text="It appears you did not set your Telegram username. "
                         "Open Telegram profile settings and set your username to continue",
                    protect_content=True,
                )

        raise APIError(APIError.INTERNAL, "Unexpected callback")
