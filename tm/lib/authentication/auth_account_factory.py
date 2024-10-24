import uuid
from psycopg2.extensions import cursor
from psycopg2.errors import UniqueViolation
from typing import Optional, Dict, Type, Tuple
from pydantic import BaseModel
import json

from .auth_account import AuthAccount, AuthAccountWithState, logger, AuthAccountData, sanitize_username, PlatformType
from ..common.api_error import APIError
from .whatsapp_dialog import WhatsappDialog
from .instagram_dialog import InstagramDialog
from .auth0_account import Auth0Account
from .telegram_dialog import TelegramDialog
from ..creator import  Creator
from ..country_cache import CountryCache
from ..common.database import Database

class DefaultAuthAccount(AuthAccountWithState[BaseModel]):
    pass

AUTH_ACC_TYPES: Dict[str, Type[AuthAccountWithState]] = {
    "admin": DefaultAuthAccount,
    "wa": WhatsappDialog,
    "ig": InstagramDialog,
    "go": Auth0Account,
    "tw": Auth0Account,
    "tg": TelegramDialog,
    "nowhere": DefaultAuthAccount,
}


def construct_auth_account(
        account_id: uuid.UUID,
        platform: PlatformType,
        userid: str,
        username: str | None,
        creator_id: uuid.UUID | None,
        account_data: Optional[AuthAccountData],
        notifications: bool,
        password_hashed: Optional[bytes],
        password_salt: Optional[bytes],
        current_state: Optional[str],
) -> AuthAccount:
    class_type = AUTH_ACC_TYPES.get(platform, None)
    if not class_type:
        logger.error(f"Unknown auth account type {platform}")
        raise APIError(APIError.INTERNAL, "Unexpected error. Please, contact customer support")

    return class_type(
        account_id=account_id, platform=platform, userid=userid, username=username,
        creator_id=creator_id, account_data=account_data, notifications=notifications,
        password_hashed=password_hashed, password_salt=password_salt,
        current_state=class_type.deserialize_state(current_state),
    )


class AuthAccountFactory:
    @staticmethod
    def create_or_update(
            platform: PlatformType,
            userid: str,
            username: str | None,
            cur: cursor,
    ) -> AuthAccount:
        username = username.lower() if username else None
        try:
            cur.execute(
                "INSERT INTO public.auth_account ("
                "platform, userid, username, notifications "
                ") "
                "VALUES (%s, %s, %s, True) "
                "ON CONFLICT ON CONSTRAINT platform_userid_pk DO UPDATE SET "
                "   username = excluded.username "
                "RETURNING account_id, creator_id, account_data, password_hashed, password_salt, current_state;",
                (
                    platform, userid, username,
                )
            )
        except UniqueViolation as e:
            logger.error(
                f"Failed to insert auth_account record "
                f"platform={platform} userid={userid} username={username}: {e}"
            )

            Database.rollback()
            cur = Database.begin()
            cur.execute(
                "SELECT userid FROM public.auth_account WHERE platform=%s AND username=%s;",
                (platform, username,)
            )
            existing_user_id = cur.fetchone()
            if not existing_user_id:
                logger.critical("Was unable to insert auth_account but existing user not found")
            else:
                logger.error(
                    f"Existing user with the same username found: "
                    f"platform={platform} userid={existing_user_id}"
                )

            raise APIError(APIError.INTERNAL, "Unexpected error. Please, contact customer support")

        entry = cur.fetchone()
        if not entry:
            raise APIError(APIError.INTERNAL, "Failed to create AuthAccount")

        result = construct_auth_account(
            account_id=entry[0], platform=platform, userid=userid, username=username, creator_id=entry[1],
            account_data=AuthAccountData.model_validate_json(entry[2]) if entry[2] else None,
            notifications=True, password_hashed=entry[3], password_salt=entry[4],
            current_state=entry[5],
        )

        return result

    @staticmethod
    def get_by_userid(platform: PlatformType, userid: str, cur: cursor) -> AuthAccount | None:
        logger.debug(
            f"get_by_userid "
            f"platform = {platform}, "
            f"userid = {userid}, "
        )

        cur.execute(
            "SELECT "
            "account_id, platform, userid, username, creator_id, account_data, notifications, "
            "password_hashed, password_salt, current_state "
            "FROM public.auth_account "
            "WHERE platform = %s AND userid = %s;",
            (platform, userid,)
        )

        entry = cur.fetchone()
        if entry is None:
            return None

        account_data = AuthAccountData.model_validate_json(entry[5]) if entry[5] else None
        return construct_auth_account(
            account_id=entry[0], platform=platform, userid=userid, username=entry[3],
            creator_id=entry[4], account_data=account_data, notifications=entry[6],
            password_hashed=bytes(entry[7]) if entry[7] else None,
            password_salt=bytes(entry[8]) if entry[8] else None,
            current_state=entry[9],
        )

    @staticmethod
    def get_by_username(platform: PlatformType, username: str, cur: cursor) -> AuthAccount | None:
        username = sanitize_username(platform, username)
        cur.execute(
            "SELECT "
            "account_id, platform, userid, username, creator_id, account_data, notifications, "
            "password_hashed, password_salt, current_state "
            "FROM public.auth_account "
            "WHERE platform = %s AND username = %s;",
            (platform, username,)
        )

        entry = cur.fetchone()
        if entry is None:
            return None

        account_data = AuthAccountData.model_validate_json(entry[5]) if entry[5] else None
        return construct_auth_account(
            account_id=entry[0], platform=platform, userid=entry[2], username=username,
            creator_id=entry[4], account_data=account_data, notifications=entry[6],
            password_hashed=bytes(entry[7]) if entry[7] else None,
            password_salt=bytes(entry[8]) if entry[8] else None,
            current_state=entry[9],
        )

    @staticmethod
    def load_creator_accounts(creator_id: uuid.UUID, cur: cursor) -> list['AuthAccount']:
        logger.debug(
            f"load_creator_accounts "
            f"creator_id = {creator_id}, "
        )

        cur.execute(
            f"SELECT "
            f"account_id, platform, userid, username, creator_id, account_data, notifications, "
            f"password_hashed, password_salt, current_state "
            f"FROM public.auth_account "
            f"WHERE creator_id = %s;",
            (creator_id,)
        )

        result = []
        for entry in cur:
            account_data = AuthAccountData.model_validate_json(entry[5]) if entry[5] else None
            result.append(construct_auth_account(
                account_id=entry[0], platform=entry[1], userid=entry[2], username=entry[3],
                creator_id=entry[4], account_data=account_data, notifications=entry[6],
                password_hashed=bytes(entry[7]) if entry[7] else None,
                password_salt=bytes(entry[8]) if entry[8] else None,
                current_state=entry[9]
            ))
        return result

    @staticmethod
    def get_auth_account_with_creator(
            platform: PlatformType,
            userid: str,
            cur: cursor,
            with_removed: bool = False,
    ) -> Tuple[AuthAccount, Creator | None]:
        cur.execute(
            f"SELECT "
            "aa.account_id, aa.platform, aa.userid, aa.username, "
            "aa.creator_id, aa.account_data, aa.notifications, "
            "aa.password_hashed, aa.password_salt, aa.current_state, "
            "c.creator_id, c.reg_datetime, c.country, c.personal_info, c.removed "
            f"FROM public.auth_account AS aa "
            f"LEFT JOIN public.creator AS c "
            f"ON aa.creator_id = c.creator_id "
            f"WHERE aa.platform = %s AND aa.userid = %s;",
            (platform, userid,),
        )

        entry = cur.fetchone()
        if not entry:
            raise APIError(APIError.INTERNAL, "Unknown social media account")

        account_data = AuthAccountData.model_validate_json(entry[5]) if entry[5] else None
        auth_account = construct_auth_account(
            account_id=entry[0], platform=platform, userid=userid, username=entry[3],
            creator_id=entry[4], account_data=account_data, notifications=entry[6],
            password_hashed=bytes(entry[7]) if entry[7] else None,
            password_salt=bytes(entry[8]) if entry[8] else None,
            current_state=entry[9],
        )

        creator = None
        creator_id = entry[10]
        if creator_id:
            removed = entry[14]
            if not removed or with_removed:
                personal_info = json.loads(entry[13]) if entry[13] is not None else None
                country = CountryCache.get_country(entry[12]) if entry[12] else None
                creator = Creator(
                    creator_id=creator_id,
                    reg_datetime=entry[11],
                    country=country,
                    personal_info=personal_info,
                    removed=removed,
                )

        return auth_account, creator

