import logging
import re
from pydantic import BaseModel, Field, model_validator
import uuid
from psycopg2.extensions import cursor
from typing import Dict, Optional, Literal, TypeVar, Any, Generic
import hashlib
import os

from ..common.api_error import APIError
from ..common.config import Config
from ..creator import Creator
from ..creator_loader import CreatorLoader

logger = logging.getLogger(__name__)
PHONE_NUMBER_RE = re.compile(r"^\+[0-9]{4,15}$")


def sanitize_phone_number(phone_number: str) -> str:
    match = PHONE_NUMBER_RE.match(phone_number.strip())
    if match is None:
        raise APIError(APIError.WRONG_PARAMETERS, f"Phone number is not correct")
    return match[0]


TG_USERNAME_RE = re.compile(r"^@?([\w](?!.*?\.{2})[\w.]{1,28}[\w])$")


def sanitize_tg_username(username: str) -> str:
    match = TG_USERNAME_RE.match(username.strip())
    if match is None:
        raise APIError(APIError.WRONG_PARAMETERS, f"Telegram username not correct")
    return match.group(1)


TG_USERID_RE = re.compile(r"^[0-9]+$")


def check_tg_userid(userid: str) -> None:
    if TG_USERID_RE.match(userid) is None:
        raise APIError(APIError.WRONG_PARAMETERS, f"Telegram userid not correct")


IG_USERNAME_RE = re.compile(r"^@?([\w](?!.*?\.{2})[\w.]{1,28}[\w])$")


def sanitize_ig_username(username: str) -> str:
    match = IG_USERNAME_RE.match(username.strip())
    if match is None:
        raise APIError(APIError.WRONG_PARAMETERS, f"Instagram username not correct")
    return match.group(1)


IG_USERID_RE = re.compile(r"^(mc_)?[0-9]+$")


def check_ig_userid(userid: str) -> None:
    if IG_USERID_RE.match(userid) is None:
        raise APIError(APIError.WRONG_PARAMETERS, f"Instagram userid not correct")


EMAIL_RE = re.compile("^\w+([\.-]?\w+)*@\w+([\.-]?\w+)*(\.\w{2,3})+$")


def sanitize_email(email: str) -> str:
    match = EMAIL_RE.match(email.strip())
    if match is None:
        raise APIError(APIError.WRONG_PARAMETERS, f"Email not correct")
    return match[0]


TW_USERNAME_RE = re.compile("^@?((\w){1,15})$")


def sanitize_tw_username(username: str) -> str:
    match = TW_USERNAME_RE.match(username.strip())
    if match is None:
        raise APIError(APIError.INSTAGRAM_ERROR, f"Twitter username not correct")
    return match.group(1)


PlatformType = Literal["ig", "go", "tw", "wa", "tg", "admin", "nowhere"]


def platform_name(platform: PlatformType) -> str | None:
    match platform:
        case "tg": return "telegram"
        case "ig": return "instagram"
        case "wa": return "whatsapp"
        case "go": return "google"
        case "tw": return "twitter"

    return None


def get_platform_name(platform: PlatformType) -> str:
    match platform:
        case "nowhere":
            return "Nowhere"
        case "go":
            return "Google"
        case "tw":
            return "Twitter/X"
        case "ig":
            return "Instagram"
        case "wa":
            return "Whatsapp"
        case "tg":
            return "Telegram"
    raise APIError(APIError.INTERNAL, f"Unknown platform {platform}")


ARBITRARY_USERNAME_REGEXP = re.compile("^[^\'\-\"/\\\]+$")


def check_arbitrary_username(username: str) -> str:
    match = ARBITRARY_USERNAME_REGEXP.match(username.strip())
    if match is None:
        raise APIError(APIError.INSTAGRAM_ERROR, f"Username not correct")
    return match.group(0)


def sanitize_username(platform: PlatformType, username: str) -> str:
    match platform:
        case "tg": return sanitize_tg_username(username)
        case "ig": return sanitize_ig_username(username)
        case "go": return sanitize_email(username)
        case "wa": return sanitize_phone_number(username)
        case "tw": return sanitize_tw_username(username)
        case "admin" | "nowhere": return check_arbitrary_username(username)

    raise APIError(APIError.INTERNAL, f"Unknown social platform {platform}")


class SocialReference(BaseModel):
    platform: PlatformType
    username: Optional[str] = Field(default=None)
    userid: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def validate_self(self) -> 'SocialReference':
        match self.platform:
            case "wa":
                if self.username and self.userid:
                    raise APIError(
                        APIError.WRONG_PARAMETERS,
                        f"Either username or userid should be set - not both!"
                    )

                if self.username:
                    self.username = sanitize_phone_number(self.username)
                elif self.userid:
                    check_ig_userid(self.userid)
                else:
                    raise APIError(
                        APIError.WRONG_PARAMETERS,
                        f"Either username or userid should be set - not both!"
                    )

            case "tg":
                if self.username and self.userid:
                    raise APIError(
                        APIError.WRONG_PARAMETERS,
                        f"Either username or userid should be set - not both!"
                    )

                if self.username:
                    self.username = sanitize_tg_username(self.username)
                elif self.userid:
                    check_tg_userid(self.userid)
                else:
                    raise APIError(
                        APIError.WRONG_PARAMETERS,
                        f"Either username or userid should be set - not both!"
                    )

            case "ig":
                if self.username and self.userid:
                    raise APIError(
                        APIError.WRONG_PARAMETERS,
                        f"Either username or userid should be set - not both!"
                    )

                if self.username:
                    self.username = sanitize_ig_username(self.username)
                elif self.userid:
                    check_ig_userid(self.userid)
                else:
                    raise APIError(
                        APIError.WRONG_PARAMETERS,
                        f"Either username or userid should be set - not both!"
                    )

            case "go":
                if not self.username:
                    raise APIError(
                        APIError.WRONG_PARAMETERS,
                        f"email should be set"
                    )

                self.username = sanitize_email(self.username)

            case "tw":
                if not self.username:
                    raise APIError(
                        APIError.WRONG_PARAMETERS,
                        f"Twitter hande should be set"
                    )

                self.username = sanitize_tw_username(self.username)

            case unknown:
                raise APIError(
                    APIError.OBJECT_NOT_FOUND,
                    f"Platform {unknown} is not supported"
                )

        return self


class AuthAccountData(BaseModel):
    name: Optional[str] = None
    follower_count: Optional[int] = None
    profile_pic: Optional[str] = None
    state: Optional[Dict] = Field(default=None, exclude=True)


class AuthAccount(BaseModel):
    account_id: uuid.UUID
    platform: PlatformType
    userid: str
    username: str | None
    creator_id: Optional[uuid.UUID] = None
    account_data: Optional[AuthAccountData] = None
    notifications: bool

    password_hashed: Optional[bytes] = Field(None, exclude=True)
    password_salt: Optional[bytes] = Field(None, exclude=True)

    async def send_message(self, message: str | None, admin_message: str | None, category: str | None = None) -> None:
        logger.info("AuthAccount.send_message not implemented")

    def update_username(self, new_username: str | None, cur: cursor) -> None:
        new_username = new_username.lower() if new_username else None
        cur.execute(
            "UPDATE public.auth_account "
            "SET username = %s "
            "WHERE account_id = %s;",
            (new_username, self.account_id)
        )

    async def update_account_data(self, account_data: AuthAccountData, cur: cursor, **_params: Any) -> None:
        self.account_data = account_data
        cur.execute(
            "UPDATE public.auth_account "
            "SET account_data = %s "
            "WHERE account_id = %s;",
            (self.account_data.model_dump_json(), self.account_id,)
        )

    def set_notifications_enabled(self, enabled: bool, cur: cursor) -> None:
        cur.execute(
            f"UPDATE public.auth_account "
            f"SET notifications = %s "
            f"WHERE account_id = %s;",
            (enabled, self.account_id,)
        )

    def link_creator(self, creator_id: uuid.UUID, cur: cursor) -> None:
        cur.execute(
            "UPDATE public.auth_account "
            "SET creator_id = %s "
            "WHERE account_id = %s;",
            (creator_id, self.account_id,)
        )

    def get_website_url(self) -> str:
        if not self.username:
            raise APIError(APIError.INTERNAL, f"Your {platform_name(self.platform)} account has no username")

        match self.platform:
            case "ig":
                return f"https://instagram.com/{self.username}"
            case "tw":
                return f"https://x.com/{self.username}"
            case "go":
                return f"{Config.USER_UI_BASE}/go/{self.username}"
            case "wa":
                return f"{Config.USER_UI_BASE}/wa/{self.username}"
            case "tg":
                return f"https://t.me/{self.username}"

        raise APIError(
            APIError.INTERNAL,
            f"Unable to create website link for user from platform {self.platform}"
        )

    def check_password(self, password: str) -> None:
        if not self.password_hashed:
            return

        if not self.password_salt:
            raise APIError(
                APIError.INTERNAL,
                f"Your account is not active. Contact support please."
            )

        password_hash = hashlib.md5(password.encode('utf-8') + self.password_salt).digest()
        if password_hash != self.password_hashed:
            raise APIError(
                APIError.LOGIN_ERROR,
                "Login or password incorrect"
            )

    def update_password(self, old_password: str, new_password: str, cur: cursor) -> None:
        if self.password_hashed is not None:
            self.check_password(old_password)

        new_salt = os.urandom(16)
        new_password_hash = hashlib.md5(new_password.encode('utf-8') + new_salt).digest()
        cur.execute(
            "UPDATE public.auth_account "
            "SET password_hashed = %s, password_salt = %s "
            "WHERE account_id = %s;",
            (new_password_hash, new_salt, self.account_id,)
        )

    async def process_event(self, _event_type: str, _data: Any, cur: cursor) -> None:
        raise APIError(APIError.INTERNAL, "AuthAccount.process_event")

    def get_creator(self, cur: cursor, with_removed: bool = False) -> Creator | None:
        return CreatorLoader.get_creator_by_id(self.creator_id, cur, with_removed)

    def commit_current_state(self, cur: cursor) -> None:
        pass

    async def send_account_reminder(self) -> None:
        await self.send_message(
            message=(
                "ℹ️ You haven't yet added a receiving account where you want to accept incoming payments. "
                "Open the app and add it now to activate payment options."
            ),
            admin_message=None,
        )

    async def send_referral_notification(self) -> None:
        pass

    async def send_referree_notification(self) -> None:
        pass


StateType = TypeVar("StateType", bound=BaseModel)

class AuthAccountWithState(AuthAccount, Generic[StateType]):
    current_state: Optional[StateType] = Field(None, exclude=True)

    @staticmethod
    def deserialize_state(json_data: str | None) -> StateType | None:
        if json_data:
            logger.error("Unexpected behavior: auth account should not have state but there's value in DB")
            raise APIError(APIError.INTERNAL, "Unexpected error. Please, contact customer support")

        return None

    def commit_current_state(self, cur: cursor) -> None:
        cur.execute(
            "UPDATE public.auth_account SET current_state = %s WHERE account_id = %s;",
            (self.current_state.model_dump_json() if self.current_state else None, self.account_id,)
        )
