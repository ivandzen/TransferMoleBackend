import logging
from typing import Optional, Any
import requests
from pydantic import BaseModel
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from psycopg2.extensions import cursor

from .profile_picture_saver import get_profile_picture_url
from ..common.api_error import APIError
from ..common.config import Config
from .auth_account import AuthAccountWithState, AuthAccountData
from ..authentication.profile_picture_saver import save_telegram_profile_picture
from ..telegram.inline_form import InlineForm
from ..telegram.startup_page import StartupPage, Callback as StartupCallback
from ..telegram.whack_a_mole import WhackAMolePage, WhackAMoleBalancePage
from ..telegram import TelegramBot
from ..creator_points import REFERREE_POINTS, REFERRAL_POINTS

logger = logging.getLogger(__name__)


class TelegramDialogState(BaseModel):
    profile_pic_id: Optional[str] = None

TELEGRAM_FORM = InlineForm(
    pages={
        "startup": StartupPage(),
        "whack_a_mole": WhackAMolePage(),
        "whack_a_mole_balance": WhackAMoleBalancePage(),
    },
    init_page="startup",
)


TASK_CAPTION = """
🔥🔥🔥 *Want to earn {remaining_to_earn} bonus points?*
\nSeason 2 of our play\-to\-earn game "Whack\-a\-mole" is just around the corner and it will be packed with a $100,000 price pool and cool giveaways\.🎁 
\nGet a headstart with *up to {remaining_to_earn} points* for completion of the following tasks:
\n_Note: to view your balance, click "Play\-to\-earn" in the main menu\._
"""


class TelegramDialog(AuthAccountWithState[TelegramDialogState]):
    @staticmethod
    def deserialize_state(json_data: str | None) -> TelegramDialogState | None:
        if json_data:
            return TelegramDialogState.model_validate_json(json_data)

        return None

    async def update_account_data(self, account_data: AuthAccountData, cur: cursor, **params: Any) -> None:
        update: Update | None = params.get("update", None)
        if not update:
            logger.error("Field 'update' not set for update_account_data")
            raise APIError(APIError.INTERNAL, "Unexpected error. Please, contact customer support")

        if not self.current_state:
            self.current_state = TelegramDialogState()

        if self.current_state.profile_pic_id != account_data.profile_pic:
            if account_data.profile_pic:
                self.current_state.profile_pic_id = account_data.profile_pic
                account_data.profile_pic = await save_telegram_profile_picture(
                    self.userid, update.get_bot(), account_data.profile_pic
                )
        else:
            account_data.profile_pic = get_profile_picture_url("tg", self.userid)

        await super().update_account_data(account_data, cur)

    async def send_message(self, message: str | None, admin_message: str | None, category: str | None = None) -> None:
        if admin_message:
            requests.post(
                url=Config.MAKE_HOOK,
                json={
                    "platform": "telegram",
                    "userid": self.userid,
                    "message": None,
                    "admin_message": admin_message,
                    "category": f'{category}',
                    "tmuuid": str(self.creator_id),
                }
            )

        if not self.notifications or not message:
            return

        await TelegramBot.instance.send_message(
            chat_id=self.userid,
            text=message,
        )


    async def process_start_event(self, data: Update, cur: cursor) -> None:
        if not data.effective_user or not data.message:
            logger.warning("There's no effective user or no message of update event")
            return

        await TELEGRAM_FORM.show(data.message, data.effective_user, self.get_creator(cur))
        self.commit_current_state(cur)

    async def process_community_event(self, data: Update, cur: cursor) -> None:
        if not data.effective_user or not data.message:
            logger.warning("There's no effective user or no message of update event")
            return

        await data.message.reply_text(
            text="Join our official community channels to stay tuned:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(text="Telegram", url="https://t.me/transfermole")],
                [InlineKeyboardButton(text="X/Twitter", url="https://x.com/GoTransferMole")],
                [InlineKeyboardButton(text="Warpcast", url="https://warpcast.com/transfermole")],
                [InlineKeyboardButton(text="Instagram", url="https://www.instagram.com/gotransfermole")],
            ])
        )

    async def process_message_event(self, data: Update, cur: cursor) -> None:
        pass

    async def process_event(self, event_type: str, data: Update, cur: cursor) -> None:
        match event_type:
            case "start": await self.process_start_event(data, cur)
            case "community": await self.process_community_event(data, cur)
            case "message": await self.process_message_event(data, cur)
            case "callback":
                if not data.callback_query or not data.callback_query.data:
                    logger.error("Unable to process event: data.callback_query is None")
                    return

                await data.callback_query.answer()
                await TELEGRAM_FORM.process_callback_query(
                    data.callback_query.data,
                    data.callback_query.message,
                    data.effective_user,
                    self.get_creator(cur),
                    self,
                )
            case unknown: raise APIError(APIError.INTERNAL, f"TelegramDialog: Unknown event type {unknown}")

    async def send_account_reminder(self) -> None:
        await TelegramBot.instance.send_message(
            chat_id=self.userid,
            text=(
                "ℹ️ You haven't yet added a receiving account where you want to accept incoming payments. "
                "Open the app and add it now to activate payment options."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(text="Open App", callback_data=StartupCallback.DASHBOARD)]
            ])
        )

    async def send_referral_notification(self) -> None:
        await TelegramBot.instance.send_message(
            chat_id=self.userid,
            text=f"Congratulations!🎉 You just earned +{REFERRAL_POINTS} points for a new user you referred.",
        )

    async def send_referree_notification(self) -> None:
        await TelegramBot.instance.send_message(
            chat_id=self.userid,
            text=f"Congratulations!🎉 You just claimed your signup reward of +{REFERREE_POINTS} points. Click Menu->Play-to-Earn for more details",
        )