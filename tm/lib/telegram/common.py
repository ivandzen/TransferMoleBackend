from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Message
import asyncio

from ..authentication.access_token import create_access_token
from ..authentication.auth_account import AuthAccount
from ..common.config import Config
from ..creator import Creator

DASHBOARD_LINK_LIFETIME_SEC = 10

async def enter_message(path: str, message: Message, auth_account: AuthAccount) -> Message:
    return await message.reply_text(
        text=f"Click within {DASHBOARD_LINK_LIFETIME_SEC} seconds 🕐 Access token will expire afterwards",
        protect_content=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                text="Continue",
                url= f"{Config.USER_UI_BASE}/{path}?access_token={create_access_token(auth_account)}",
            )],
        ])
    )


async def dashboard_message(creator: Creator | None, message: Message, auth_account: AuthAccount) -> None:
    if not creator:
        msg = await enter_message("register", message, auth_account)
    else:
        msg = await enter_message("dashboard", message, auth_account)
    await asyncio.sleep(DASHBOARD_LINK_LIFETIME_SEC)
    await msg.delete()


async def play_game_message(creator: Creator | None, message: Message, auth_account: AuthAccount) -> None:
    if not creator:
        msg = await message.reply_text(text="You are not registered")
    else:
        msg = await enter_message("whack_a_mole", message, auth_account)

    await asyncio.sleep(DASHBOARD_LINK_LIFETIME_SEC)
    await msg.delete()