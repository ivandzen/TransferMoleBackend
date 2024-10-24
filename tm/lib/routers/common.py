from datetime import timedelta
import asyncio
from fastapi import Request, Depends
from pydantic import BaseModel
from psycopg2.extensions import cursor
import dataclasses
from typing import Annotated, List, Tuple
from fastapi.security import OAuth2PasswordBearer
import jwt
import logging

from ..creator import Creator
from ..common.api_error import APIError
from ..common.config import Config
from ..creator_loader import CreatorLoader
from ..authentication.auth_account import AuthAccount
from ..authentication.auth_account_factory import AuthAccountFactory
from ..authentication.access_token import AccessToken
from ..notification_utils import send_notification
from ..notification import UserRestored, UserRegistered
from ..payout.account_factory import AccountFactory

logger = logging.getLogger(__name__)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/admin/login")
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/admin/login", auto_error=False)


def database_cursor(request: Request) -> cursor:
    return request.state.cursor

def get_client_ip(request: Request) -> str | None:
    client = request.client
    if not client:
        return None

    return client.host


def check_access_token(access_token: str, cur: cursor) -> Tuple[AuthAccount, Creator | None]:
    try:
        token = AccessToken.model_validate(
            jwt.decode(
                access_token,
                Config.SERVER_PUBLIC_KEY,
                algorithms=["RS256"],
            )
        )

        return AuthAccountFactory.get_auth_account_with_creator(
            platform=token.platform, userid=token.userid, cur=cur
        )

    except Exception as error:
        raise APIError(APIError.ACCESS_ERROR, str(error))


@dataclasses.dataclass
class Context:
    cur: cursor
    access_token: str
    auth_account: AuthAccount
    creator: Creator | None
    client_ip: str | None

@dataclasses.dataclass
class OptionalContext:
    cur: cursor
    access_token: str | None
    auth_account: AuthAccount | None
    creator: Creator | None
    client_ip: str | None


async def required_access_token_ctx(
        access_token: Annotated[str, Depends(oauth2_scheme)],
        cur: Annotated[cursor, Depends(database_cursor)],
        client_ip: Annotated[str | None, Depends(get_client_ip)],
) -> Context:
    auth_account, creator = check_access_token(access_token, cur)
    if not auth_account:
        raise APIError(APIError.ACCESS_ERROR, "Authentication account not found")

    return Context(
        cur=cur,
        access_token=access_token,
        auth_account=auth_account,
        creator=creator,
        client_ip=client_ip,
    )


async def optional_access_token_ctx(
        access_token: Annotated[str | None, Depends(optional_oauth2_scheme)],
        cur: Annotated[cursor, Depends(database_cursor)],
        client_ip: Annotated[str | None, Depends(get_client_ip)],
) -> OptionalContext:
    if access_token:
        auth_account, creator = check_access_token(access_token, cur)
        if not auth_account:
            raise APIError(APIError.ACCESS_ERROR, "Authentication account not found")

        return OptionalContext(
            cur=cur,
            access_token=access_token,
            auth_account=auth_account,
            creator=creator,
            client_ip=client_ip,
        )

    return OptionalContext(
        cur=cur,
        access_token=None,
        auth_account=None,
        creator=None,
        client_ip=client_ip,
    )


class Duration(BaseModel):
    weeks: int
    days: int
    hours: int
    minutes: int

    def to_timedelta(self) -> timedelta:
        return timedelta(
            weeks=self.weeks,
            days=self.days,
            hours=self.hours,
            minutes=self.minutes
        )


WAIT_FOR_ACCOUNT_AFTER_REG_SECS = 60


class RegisterUserNotification:
    NONE = 0
    CREATED = 1
    RESTORED = 2


def create_or_restore_user(auth_account: AuthAccount, creator: Creator | None, cur: cursor) -> None:
    if not auth_account.creator_id and creator:
        logger.error(
            f"create_or_restore_user: auth_account({auth_account.platform}, {auth_account.userid}) "
            f"Creator {creator.creator_id} provided")
        raise APIError(APIError.INTERNAL, "Unexpected behavior. Please, contact customer support")

    notification = RegisterUserNotification.NONE
    if auth_account.creator_id:
        if not creator:
            creator = CreatorLoader.restore_creator(auth_account.creator_id, cur)
            notification = RegisterUserNotification.RESTORED
    else:
        creator = CreatorLoader.create_new(cur)
        auth_account.link_creator(creator.creator_id, cur)
        notification = RegisterUserNotification.CREATED

    async def after_user_registered(auth_accounts: List[AuthAccount], cur2: cursor) -> None:
        await asyncio.sleep(WAIT_FOR_ACCOUNT_AFTER_REG_SECS)
        accounts = AccountFactory.get_creator_owned_accounts(creator, cur2)
        if len(accounts) == 0:
            for auth_acc in auth_accounts:
                await auth_acc.send_account_reminder()

    match notification:
        case RegisterUserNotification.NONE: pass
        case RegisterUserNotification.RESTORED:
            send_notification(creator.creator_id, UserRestored(), after_user_registered)
        case RegisterUserNotification.CREATED:
            send_notification(creator.creator_id, UserRegistered(), after_user_registered)
