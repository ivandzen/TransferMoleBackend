from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, User, MenuButtonWebApp, WebAppInfo
import logging
from typing import List, Any

from .inline_form import BaseFormPage
from .. import GameTasks
from ..common.database import Database
from ..authentication.auth_account import AuthAccount
from ..common.config import Config
from ..common.api_error import APIError
from ..creator import Creator
from .common import dashboard_message, play_game_message
from ..creator_points import CreatorPoints, load_creator_points

logger = logging.getLogger(__name__)


caption_header = """
Whack\-a\-Mole is a part of TransferMole's $100,000 incentive program for early users and community members\. 💰

We just finished Season 1 of the game and will be shortly deploying Season 2, which will include a new game and new exciting opportunities to earn\. 💜

➡️ To qualify you must signup on TransferMole with your Telegram username\.
"""


class WhackAMoleCallback:
    SIGN_UP = "whack_a_mole.sign_up"
    BALANCE = "whack_a_mole.my_balance"
    MAIN_MENU = "whack_a_mole.main_menu"
    PLAY = "whack_a_mole.play"


class WhackAMolePage(BaseFormPage):
    async def picture(self, _user: User, creator: Creator | None) -> str:
        return "https://app.transfermole.com/pictures/mega_mole.jpg"

    async def caption(self, _user: User, creator: Creator | None) -> str | None:
        return caption_header

    async def markup(self, _user: User, creator: Creator | None) -> InlineKeyboardMarkup | None:
        buttons: List[Any] = []
        if creator:
            buttons.append([InlineKeyboardButton(text=f"My Points Balance", callback_data=WhackAMoleCallback.BALANCE)])
            buttons.append([MenuButtonWebApp(text="Play ▶️", web_app=WebAppInfo(url=f"{Config.USER_UI_BASE}/enter_telegram/whack_a_mole"))])
        else:
            buttons.append([InlineKeyboardButton(text="Sign Up", callback_data=WhackAMoleCallback.SIGN_UP)])

        buttons.append([InlineKeyboardButton(text="Main Menu", callback_data=WhackAMoleCallback.MAIN_MENU)])
        return InlineKeyboardMarkup(buttons)

    async def process_callback_query(
            self,
            query: str,
            message: Message,
            user: User,
            creator: Creator | None,
            auth_account: AuthAccount,
    ) -> str | None:
        match query:
            case WhackAMoleCallback.SIGN_UP:
                await dashboard_message(creator, message, auth_account)

            case WhackAMoleCallback.MAIN_MENU: return "startup"
            case WhackAMoleCallback.BALANCE: return "whack_a_mole_balance"
            case WhackAMoleCallback.PLAY:
                await play_game_message(creator, message, auth_account)
                return None

        raise APIError(APIError.INTERNAL, "Unexpected callback")

def get_user_balance(userid: int, creator: Creator) -> CreatorPoints:
    try:
        cur = Database.begin()
        points = load_creator_points(creator.creator_id, str(userid), cur)
        Database.commit()
        return points

    except Exception as e:
        Database.rollback()
        logger.error(f"Failed to process get_user_balance({userid}, {creator.creator_id}): {e}")
        raise APIError(APIError.INTERNAL, "Failed to get user balance")


class WhackAMoleBalanceCallback:
    MAIN_MENU = "whack_a_mole_balance.main_menu"


class WhackAMoleBalancePage(BaseFormPage):
    async def picture(self, _user: User, creator: Creator | None) -> str:
        return "https://app.transfermole.com/pictures/mega_mole.jpg"

    async def caption(self, user: User, creator: Creator | None) -> str | None:
        if not creator:
            return "You are not registered"

        points = get_user_balance(user.id, creator)
        try:
            cur = Database.begin()
            tasks = GameTasks.get_all_tasks(creator.creator_id, cur)
            Database.commit()
            message = f"Your Whack-a-Mole balance is {points.total_points()} pts\n"
            for task_name, task_points in points.points.items():
                message += f"\n▪️{task_points.amount} pts - {tasks[task_name].root.task_data.description}"
        except Exception as e:
            Database.rollback()
            logger.error(f"Failed to get user tasks ({user.id}, {creator.creator_id}): {e}")
            raise APIError(APIError.INTERNAL, "Failed to get user balance")

        return message.replace('-', '\-').replace('.', '\.')

    async def markup(self, _user: User, creator: Creator | None) -> InlineKeyboardMarkup | None:
        return InlineKeyboardMarkup([
            [MenuButtonWebApp(text="Play ▶️", web_app=WebAppInfo(url=f"{Config.USER_UI_BASE}/enter_telegram/whack_a_mole"))],
            [InlineKeyboardButton(text="Main Menu", callback_data=WhackAMoleBalanceCallback.MAIN_MENU)],
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
            case WhackAMoleBalanceCallback.MAIN_MENU: return "startup"

        raise APIError(APIError.INTERNAL, "Unexpected callback")
