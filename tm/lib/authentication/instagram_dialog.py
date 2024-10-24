import logging
import requests
from pydantic import BaseModel
from psycopg2.extensions import cursor
from typing import Any

from .profile_picture_saver import save_profile_picture
from ..common.config import Config
from .instagram_api import InstagramAPI
from .auth_account import AuthAccountWithState, AuthAccountData

logger = logging.getLogger(__name__)


class InstagramDialog(AuthAccountWithState[BaseModel]):
    async def send_message(self, message: str | None, admin_message: str | None, category: str | None = None) -> None:
        if not self.notifications and not admin_message:
            return

        if self.userid[:3] == "mc_":
            requests.post(
                url=Config.MAKE_HOOK,
                json={
                    "platform": "instagram",
                    "userid": self.userid[3:],
                    "message": f'"{message}"' if message else None,
                    "admin_message": f'"{admin_message}"' if admin_message else None,
                    "category": f'{category}',
                    "tmuuid": str(self.creator_id),
                }
            )
        elif message:
            InstagramAPI.send_simple_message(self.userid, message)

    async def update_account_data(self, account_data: AuthAccountData, cur: cursor, **params: Any) -> None:
        account_data.profile_pic = save_profile_picture(self.platform, self.userid, account_data.profile_pic)
        await super().update_account_data(account_data, cur, **params)
