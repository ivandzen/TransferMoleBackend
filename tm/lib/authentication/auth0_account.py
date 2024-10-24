import requests
import logging
from psycopg2.extensions import cursor
from pydantic import BaseModel
from typing import Any

from .profile_picture_saver import save_profile_picture
from .auth_account import AuthAccountWithState, AuthAccountData
from ..common.config import Config


logger = logging.getLogger(__name__)


class Auth0Account(AuthAccountWithState[BaseModel]):
    async def send_message(self, message: str | None, admin_message: str | None, category: str | None = None) -> None:
        if not self.notifications and not admin_message:
            return

        match self.platform:
            case "go":
                requests.post(
                    url=Config.MAKE_HOOK,
                    json={
                        "platform": "google",
                        "userid": self.username,
                        "message": f'"{message}"' if message else None,
                        "admin_message": f'"{admin_message}"' if admin_message else None,
                        "category": f'{category}',
                        "tmuuid": str(self.creator_id),
                    }
                )
            case "tw":
                requests.post(
                    url=Config.MAKE_HOOK,
                    json={
                        "platform": "twitter",
                        "userid": self.userid,
                        "message": f'"{message}"' if message else None,
                        "admin_message": f'"{admin_message}"' if admin_message else None,
                        "category": f'{category}',
                        "tmuuid": str(self.creator_id),
                    }
                )

    async def update_account_data(self, account_data: AuthAccountData, cur: cursor, **params: Any) -> None:
        account_data.profile_pic = save_profile_picture(self.platform, self.userid, account_data.profile_pic)
        await super().update_account_data(account_data, cur, **params)
