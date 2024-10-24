from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import logging

from ..common.config import Config
from ..whitelist import Whitelist
from ..common.api_error import APIError
from ..authentication.auth_account import AuthAccountData, SocialReference
from ..authentication.auth_account_factory import AuthAccountFactory
from ..authentication.access_token import create_access_token
from ..common.database import Database
from ..creator_loader import CreatorLoader
from ..creator_reference import CreatorReference, load_creator_by_reference


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/manychat/whatsapp", tags=["manychat-whatsapp"])


class ManychatPayload(BaseModel):
    manychat_token: str


def check_manychat_token(payload: ManychatPayload) -> None:
    if Config.MANYCHAT_TOKEN != payload.manychat_token:
        raise APIError(APIError.INVALID_TOKEN, f"MC token invalid")


@router.post("/id/{userid}")
async def manychat_whatsapp_userid(userid: str) -> JSONResponse:
    try:
        logger.info(f"manychat_whatsapp_userid(userid = {userid})")
        userid = f"mc_{userid}"
        cur = Database.begin()
        creator = load_creator_by_reference(
            CreatorReference(social=SocialReference(platform="wa", userid=userid)),
            cur
        )

        if creator is None:
            return JSONResponse(
                content={"error": f"User not found"},
                status_code=200,
            )

        return JSONResponse(
            content={"transfermole_user": creator.creator_id},
            status_code=200
        )
    except Exception as e:
        logger.error(f"Exception: {e}")
        return JSONResponse(
            content={"error": f"Unexpected error"},
            status_code=200,
        )


@router.get("/id/{userid}/whitelist")
async def manychat_whatsapp_userid_whitelist_get(userid: str, payload: ManychatPayload) -> JSONResponse:
    try:
        logger.info(f"manychat_whatsapp_userid_whitelist_get(userid = {userid})")
        check_manychat_token(payload)
        userid = f"mc_{userid}"
        cur = Database.begin()
        return JSONResponse(
            content={
                "whitelisted": Whitelist.is_whitelisted("wa", userid, cur)
            },
            status_code=200
        )
    except Exception as e:
        logger.error(f"Exception: {e}")
        return JSONResponse(
            content={"error": f"Unexpected error"},
            status_code=200,
        )


@router.post("/id/{userid}/whitelist")
async def manychat_whatsapp_userid_whitelist_post(userid: str, payload: ManychatPayload) -> JSONResponse:
    try:
        logger.info(f"manychat_whatsapp_userid_whitelist_post(userid = {userid})")
        check_manychat_token(payload)
        userid = f"mc_{userid}"
        cur = Database.begin()
        Whitelist.append_new("wa", userid, cur)
        Database.commit()
        return JSONResponse(
            content={"success": True},
            status_code=200
        )
    except Exception as e:
        Database.rollback()
        logger.error(f"Exception: {e}")
        return JSONResponse(
            content={"error": f"Unexpected error"},
            status_code=200,
        )


@router.post("/id/{userid}/register")
async def manychat_whatsapp_userid_register(userid: str, payload: ManychatPayload) -> JSONResponse:
    try:
        logger.info(f"manychat_whatsapp_userid_register(userid = {userid})")
        check_manychat_token(payload)
        username = f"+{userid}"
        userid = f"mc_{userid}"
        cur = Database.begin()
        creator = load_creator_by_reference(
            CreatorReference(social=SocialReference(platform="wa", userid=userid)),
            cur
        )

        if creator is not None:
            Database.commit()
            return JSONResponse(
                content={"error": f"Already registered"},
                status_code=200,
            )

        dialog = AuthAccountFactory.create_or_update(
            platform="wa", userid=userid, username=username, cur=cur
        )
        await dialog.update_account_data(AuthAccountData(), cur)
        Database.commit()

        return JSONResponse(
            content={
                "registration_link": f"{Config.USER_UI_BASE}/register?access_token={create_access_token(dialog)}"
            },
            status_code=200
        )
    except Exception as e:
        Database.rollback()
        logger.error(f"Exception: {e}")
        return JSONResponse(
            content={"error": f"Unexpected error"},
            status_code=200,
        )


@router.post("/id/{userid}/dashboard")
async def manychat_whatsapp_userid_dashboard(userid: str, payload: ManychatPayload) -> JSONResponse:
    try:
        logger.info(f"manychat_whatsapp_userid_dashboard(userid = {userid})")
        check_manychat_token(payload)
        userid = f"mc_{userid}"
        cur = Database.begin()
        creator = load_creator_by_reference(
            CreatorReference(social=SocialReference(platform="wa", userid=userid)),
            cur
        )

        if creator is None:
            return JSONResponse(
                content={"error": f"User not found"},
                status_code=200,
            )

        dialog = AuthAccountFactory.get_by_userid("wa", userid, cur)
        if dialog is None:
            Database.commit()
            return JSONResponse(
                content={"error": f"User not found"},
                status_code=200,
            )

        access_token = create_access_token(dialog)
        Database.commit()
        return JSONResponse(
            content={
                "dashboard_link": f"{Config.USER_UI_BASE}/dashboard?access_token={access_token}",
            },
            status_code=200,
        )
    except Exception as e:
        Database.rollback()
        logger.error(f"Exception: {e}")
        return JSONResponse(
            content={"error": f"Unexpected error"},
            status_code=200,
        )


@router.post("/id/{userid}/payment_link")
async def manychat_whatsapp_userid_payment_link(userid: str) -> JSONResponse:
    try:
        logger.info(f"manychat_whatsapp_userid_payment_link(userid = {userid})")
        userid = f"mc_{userid}"
        cur = Database.begin()
        creator = load_creator_by_reference(
            CreatorReference(social=SocialReference(platform="wa", userid=userid)),
            cur
        )

        Database.commit()
        if creator is None:
            return JSONResponse(
                content={"error": f"User not found"},
                status_code=200,
            )

        return JSONResponse(
            content={
                "payment_link": creator.get_payment_link(),
            },
            status_code=200
        )
    except Exception as e:
        Database.rollback()
        logger.error(f"Exception: {e}")
        return JSONResponse(
            content={"error": f"Unexpected error"},
            status_code=200,
        )


@router.post("/name/{uname}/payment_link")
async def manychat_whatsapp_username_payment_link(uname: str) -> JSONResponse:
    try:
        logger.info(f"manychat_whatsapp_username_payment_link(uname = {uname})")
        cur = Database.begin()
        creator = load_creator_by_reference(
            CreatorReference(social=SocialReference(platform="wa", username=uname)),
            cur
        )

        Database.commit()
        if creator is None:
            return JSONResponse(
                content={"error": f"User not found"},
                status_code=200,
            )

        return JSONResponse(
            content={
                "payment_link": creator.get_payment_link(),
            },
            status_code=200
        )
    except Exception as e:
        Database.rollback()
        logger.error(f"Exception: {e}")
        return JSONResponse(
            content={"error": f"Unexpected error"},
            status_code=200,
        )
