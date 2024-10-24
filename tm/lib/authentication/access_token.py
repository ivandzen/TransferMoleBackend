from pydantic import BaseModel
from typing import Optional
import datetime
from ..common.config import Config
import logging
from ..authentication.auth_account import AuthAccount, PlatformType
import jwt


logger = logging.getLogger(__name__)


class AccessToken(BaseModel):
    exp: datetime.datetime
    platform: PlatformType
    userid: str
    username: Optional[str] = None


def create_access_token(external_acc: AuthAccount) -> str:
    token = AccessToken(
        exp=datetime.datetime.utcnow() + Config.ACCESS_TOKEN_LIFETIME,
        platform=external_acc.platform,
        userid=external_acc.userid,
        username=external_acc.username
    )

    return jwt.encode(
        token.model_dump(),
        Config.SERVER_PRIVATE_KEY,
        algorithm="RS256",
    )
