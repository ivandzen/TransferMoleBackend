from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse, Response
import requests
from pydantic import BaseModel
from typing import Optional
import logging

from ..common.config import Config
from ..common.api_error import APIError
from ..authentication.auth_account_factory import AuthAccountFactory
from ..authentication.auth_account import AuthAccountData, PlatformType
from ..common.database import Database
from ..authentication.access_token import create_access_token
from ..authentication.auth0_session import Auth0Session


logger = logging.getLogger(__name__)
api_session = requests.Session()
router = APIRouter(prefix="/auth0", tags=["auth0"])


async def login_handler_impl(platform: PlatformType | None) -> RedirectResponse:
    match platform:
        case None:
            additional_params = None
        case "go":
            additional_params = f"&connection=google-oauth2&prompt=select_account"
        case "tw":
            additional_params = f"&connection=twitter"
        case unknown:
            raise HTTPException(status_code=500, detail=f"Platform {unknown} is not supported")

    new_session = await Auth0Session.create_new()
    redirect_url = (
        f"https://{Config.AUTH0_DOMAIN}/authorize?"
        f"client_id={Config.AUTH0_CLIENT_ID}&"
        "response_type=code&"
        f"code_challenge={new_session.challenge}&"
        "code_challenge_method=S256&"
        f"redirect_uri={Config.USER_UI_BASE}/auth0/callback&"
        f"audience=https://{Config.AUTH0_DOMAIN}/api/v2/&"
        "scope=openid%20profile%20email&"
        f"state={new_session.state}"
    )

    if additional_params:
        redirect_url += additional_params

    return RedirectResponse(redirect_url)


@router.get("/login")
async def login_handler_no_platform() -> RedirectResponse:
    return await login_handler_impl(None)


@router.get("/login/{platform}")
async def login_handler_with_platform(platform: PlatformType) -> RedirectResponse:
    return await login_handler_impl(platform)


class Auth0Userinfo(BaseModel):
    sub: str
    name: str
    picture: str
    email: Optional[str] = None
    nickname: Optional[str] = None


def get_platform(sub_prefix: str) -> PlatformType:
    match sub_prefix:
        case "google-oauth2":
            return "go"
        case "twitter":
            return "tw"
        case unknown:
            logger.error(f"Unknown sub prefix: {unknown}")
            raise APIError(APIError.INTERNAL)


async def callback_handler_impl(code: str, state: str) -> Response:
    auth0_session = await Auth0Session.get_by_state(state)
    response = api_session.post(
        f"https://{Config.AUTH0_DOMAIN}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": Config.AUTH0_CLIENT_ID,
            "client_secret": Config.AUTH0_CLIENT_SECRET,
            "code": code,
            "redirect_uri": f"{Config.USER_UI_BASE}/pay",
            "code_verifier": auth0_session.verifier,
        },
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )

    if response.status_code == 200:
        auth0_access_token = response.json()['access_token']
        response = api_session.get(
            f"https://{Config.AUTH0_DOMAIN}/userinfo",
            headers={
                "Authorization": f"Bearer {auth0_access_token}"
            }
        )

        userinfo = Auth0Userinfo.model_validate(response.json())
        cur = Database.begin()
        sub_prefix, userid = userinfo.sub.split('|')
        platform = get_platform(sub_prefix)
        if userinfo.email:
            username = userinfo.email
        elif userinfo.nickname:
            username = userinfo.nickname
        else:
            raise APIError(
                APIError.INTERNAL,
                f"Neither email nor nickname is set"
            )

        auth0_acc = AuthAccountFactory.create_or_update(
            platform=platform, userid=userid, username=username, cur=cur
        )
        await auth0_acc.update_account_data(
            AuthAccountData(
                name=userinfo.name,
                profile_pic=userinfo.picture
            ),
            cur
        )
        Database.commit()
        return RedirectResponse(f"{Config.USER_UI_BASE}/register?access_token={create_access_token(auth0_acc)}")

    else:
        logging.info(f"Error: {response.text}")
        return Response(status_code=403)


@router.post("/callback")
async def callback_handler_post(code: str, state: str) -> Response:
    return await callback_handler_impl(code, state)


@router.get("/callback")
async def callback_handler_get(code: str, state: str) -> Response:
    return await callback_handler_impl(code, state)
