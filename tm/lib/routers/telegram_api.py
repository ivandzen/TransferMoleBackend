import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel
import hmac
import hashlib
from urllib.parse import unquote
from typing import Optional, Annotated
from psycopg2.extensions import cursor

from .common import database_cursor, create_or_restore_user
from ..common.config import Config
from ..common.api_error import APIError
from ..authentication.auth_account_factory import AuthAccountFactory
from ..authentication.access_token import create_access_token


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram"])


class TgUser(BaseModel):
    allows_write_to_pm: bool
    first_name: Optional[str] = None
    id: int
    language_code: str
    last_name: Optional[str] = None
    username: Optional[str] = None


class EnterRequest(BaseModel):
    init_data: str


class EnterResponse(BaseModel):
    access_token: str


@router.post(
    path="/enter",
    response_model=EnterResponse,
    operation_id="enter"
)
async def enter(
        cur: Annotated[cursor, Depends(database_cursor)],
        enter_request: EnterRequest,
) -> EnterResponse:
    values = [chunk.split("=") for chunk in unquote(enter_request.init_data).split("&")]
    hash_str = None
    for (name, value) in values:
        if name == "hash":
            hash_str = value
            break

    if hash_str is None:
        raise APIError(APIError.INTERNAL, "Unable to login using Telegram: incorrect initData")

    init_data_lst = sorted([rec for rec in values if rec[0] != "hash"], key=lambda x: x[0])
    init_data = "\n".join([f"{rec[0]}={rec[1]}" for rec in init_data_lst])

    secret_key = hmac.new("WebAppData".encode(), Config.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
    data_check = hmac.new(secret_key, init_data.encode(), hashlib.sha256)

    if data_check.hexdigest() != hash_str:
        raise APIError(APIError.ACCESS_ERROR, "Failed to verify TG login information")

    user = None
    for (name, value) in values:
        if name == "user":
            user = TgUser.model_validate_json(value)
            break

    if user is None:
        logger.error("user field is absent in TG initData")
        raise APIError(APIError.INTERNAL, "Unexpected error. Please, contact customer support")

    if user.username is None:
        raise APIError(APIError.INTERNAL, "Your account should have username to interact with TransferMole Application")

    auth_account, creator = AuthAccountFactory.get_auth_account_with_creator(platform="tg", userid=str(user.id), cur=cur)
    create_or_restore_user(auth_account, creator, cur)
    return EnterResponse(access_token=create_access_token(auth_account))
