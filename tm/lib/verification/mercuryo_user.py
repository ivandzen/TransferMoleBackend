import datetime
from uuid import UUID
from requests import Session
import logging
from psycopg2.extensions import cursor
from dataclasses import dataclass
from pydantic import BaseModel
from typing import Optional

from ..authentication.auth_account_factory import AuthAccountFactory
from ..common.config import Config
from ..common.api_error import APIError
from ..creator import Creator
from ..verification import SUMSUB_KYC_PROVIDER

logger = logging.getLogger(__name__)
mercuryo_api_session = Session()
relogin_interval_minutes = 50
MERCURYO_API_URL={
    "Sandbox": "https://sandbox-api.mrcr.io/v1.6",
    "Prod": "https://api.mercuryo.io/v1.6",
}


class SignUpResultData(BaseModel):
    init_token: str
    init_type_token: str
    uuid: UUID


class SignUpResult(BaseModel):
    data: SignUpResultData
    status: int


class LoginResultData(BaseModel):
    init_token: str
    init_type_token: str
    user_uuid: UUID


class LoginResult(BaseModel):
    data: LoginResultData
    status: int


@dataclass
class MercuryoUser:
    user_id: UUID
    creator_id: Optional[UUID]
    email: Optional[str]
    phone: Optional[str]
    init_token: Optional[str]
    last_update: datetime.datetime

    def login(self, cur: cursor) -> str:
        now = datetime.datetime.utcnow()
        if self.init_token and (now - self.last_update).seconds < relogin_interval_minutes * 60:
            return self.init_token

        response = mercuryo_api_session.post(
            url=f"{MERCURYO_API_URL[Config.MERCURYO_MODE]}/sdk-partner/login",
            headers={"Sdk-Partner-Token": Config.MERCURYO_SDK_PARTNER_TOKEN},
            json={"user_uuid4": self.user_id}
        )

        if response.status_code != 200:
            logger.warning(f"Failed to obtain Mercuryo init token: {response.content}")
            raise APIError(APIError.INTERNAL, "Failed to prepare onramp payment")

        result = LoginResult.model_validate(response.json())
        cur.execute(
            "UPDATE public.mercuryo_user "
            "SET init_token = %s, last_update = %s "
            "WHERE user_id = %s;",
            (result.data.init_token, now, self.user_id,)
        )
        self.init_token = result.data.init_token
        self.last_update = now
        return self.init_token

    def _set_creator_id(self, creator_id: UUID, cur: cursor) -> None:
        cur.execute(
            "UPDATE public.mercuryo_user SET creator_id = %s WHERE user_id = %s;",
            (creator_id, self.user_id,)
        )

    @staticmethod
    def _get_by_email(email: str, cur: cursor) -> "MercuryoUser | None":
        cur.execute(
            "SELECT user_id, creator_id, email, phone, init_token, last_update FROM public.mercuryo_user "
            "WHERE email = %s;",
            (email,)
        )

        result = cur.fetchone()
        if not result:
            return None

        return MercuryoUser(
            user_id=result[0],
            creator_id=result[1],
            email=result[2],
            phone=result[3],
            init_token=result[4],
            last_update=result[5]
        )

    @staticmethod
    def _get_by_phone(phone: str, cur: cursor) -> "MercuryoUser | None":
        cur.execute(
            "SELECT user_id, creator_id, email, phone, init_token, last_update FROM public.mercuryo_user "
            "WHERE phone = %s;",
            (phone,)
        )

        result = cur.fetchone()
        if not result:
            return None

        return MercuryoUser(
            user_id=result[0],
            creator_id=result[1],
            email=result[2],
            phone=result[3],
            init_token=result[4],
            last_update=result[5]
        )

    @staticmethod
    def _create_new_empty(user_id: UUID, email: str | None, phone: str | None, cur: cursor) -> "MercuryoUser":
        cur.execute(
            "INSERT INTO public.mercuryo_user (user_id, email, phone) "
            "VALUES (%s, %s, %s) "
            "RETURNING last_update;",
            (user_id, email, phone,)
        )

        result = cur.fetchone()
        if not result:
            raise APIError(
                APIError.INTERNAL,
                f"Unexpected error. Please, contact customer support."
            )

        return MercuryoUser(
            user_id=user_id,
            creator_id=None,
            email=email,
            phone=phone,
            init_token=None,
            last_update=result[0]
        )

    @staticmethod
    def _create_new_linked(email: str, creator: Creator, cur: cursor) -> "MercuryoUser":
        share_token_result = SUMSUB_KYC_PROVIDER.generate_share_token(creator, "Mercuryo", cur)
        response = mercuryo_api_session.post(
            url=f"{MERCURYO_API_URL[Config.MERCURYO_MODE]}/sdk-partner/sign-up",
            headers={"Sdk-Partner-Token": Config.MERCURYO_SDK_PARTNER_TOKEN},
            json={
                "accept": True,
                "email": email,
                "share_token": share_token_result.token,
            }
        )

        if response.status_code != 200:
            logger.warning(f"Failed to obtain Mercuryo init token: {response.content}")
            raise APIError(APIError.INTERNAL, "Failed to prepare onramp payment")

        api_result = SignUpResult.model_validate(response.json())
        cur.execute(
            "INSERT INTO public.mercuryo_user (user_id, creator_id, email, init_token) "
            "VALUES (%s, %s, %s, %s) "
            "RETURNING last_update;",
            (api_result.data.uuid, creator.creator_id, email, api_result.data.init_token,)
        )

        entry = cur.fetchone()
        if not entry:
            logger.warning(f"Failed to add Mercuryo user")
            raise APIError(APIError.INTERNAL, "Failed to prepare onramp payment")

        return MercuryoUser(
            user_id=api_result.data.uuid,
            creator_id=creator.creator_id,
            email=email,
            phone=None,
            init_token=api_result.data.init_token,
            last_update=entry[0],
        )

    @staticmethod
    def get_or_create_new_empty(user_id: UUID, email: str | None, phone: str | None, cur: cursor) -> "MercuryoUser":
        if email:
            user = MercuryoUser._get_by_email(email, cur)
        elif phone:
            user = MercuryoUser._get_by_phone(phone, cur)
        else:
            raise APIError(APIError.INTERNAL, "Neither email not phone is specified for Mercuryo user")

        if not user:
            return MercuryoUser._create_new_empty(user_id, email, phone, cur)

        return user

    @staticmethod
    def get_or_create_new_linked(creator: Creator, cur: cursor) -> "MercuryoUser":
        auth_accounts = AuthAccountFactory.load_creator_accounts(creator.creator_id, cur)
        email = None
        for auth_acc in auth_accounts:
            if auth_acc.platform == "go":
                email = auth_acc.username
                break

        if not email:
            raise APIError(
                APIError.INTERNAL,
                f"email is not set for user"
            )

        user = MercuryoUser._get_by_email(email, cur)
        if not user:
            user = MercuryoUser._create_new_linked(email, creator, cur)
            return user

        if user.creator_id == creator.creator_id:
            return user

        if not user.creator_id:
            user._set_creator_id(creator.creator_id, cur)
            return user

        raise APIError(
            APIError.INTERNAL,
            f"Unable to register Mercuryo user. Because email {email} already registered."
        )
