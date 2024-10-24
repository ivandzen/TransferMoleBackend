import uuid
from psycopg2.extensions import cursor
from datetime import timedelta
from pydantic import BaseModel
from typing import Tuple
import random
import string
import re

from .common.api_error import APIError

LETTERS_AND_NUMBERS = string.ascii_uppercase + string.digits
EXPIRATION_PERIOD = timedelta(days=30)
REFERRAL_CODE_REGEXP = re.compile(r"^[a-zA-Z0-9]+$")


def check_referral_code(referral_code: str) -> str:
    referral_code = referral_code.upper()
    if not REFERRAL_CODE_REGEXP.match(referral_code):
        raise APIError(APIError.INTERNAL, "Wrong referral code")

    return referral_code


class ReferralCode(BaseModel):
    code: str


class Referrals:
    @staticmethod
    def create_new(creator_id: uuid.UUID, cur: cursor) -> ReferralCode:
        new_referral_code = ''.join([random.choice(LETTERS_AND_NUMBERS) for _ in range(10)])
        cur.execute(
            "INSERT INTO public.referrals (creator_id, referral_code) VALUES (%s, %s)"
            "ON CONFLICT (creator_id) DO NOTHING "
            "RETURNING referral_code;",
            (creator_id, new_referral_code)
        )

        entry = cur.fetchone()
        if entry is None:
            raise APIError(APIError.INTERNAL, "Referral code was already created")

        return ReferralCode(code=entry[0])

    @staticmethod
    def get_referral_code(creator_id: uuid.UUID, cur: cursor) -> ReferralCode:
        cur.execute(
            "SELECT referral_code FROM public.referrals WHERE creator_id = %s;",
            (creator_id,)
        )

        entry = cur.fetchone()
        if not entry:
            return Referrals.create_new(creator_id, cur)

        return ReferralCode(code=entry[0])

    @staticmethod
    def get_referral_id(referral_code: str, cur: cursor) -> Tuple[uuid.UUID, uuid.UUID]:
        referral_code = check_referral_code(referral_code)
        cur.execute(
            "SELECT creator_id, referred_by FROM public.referrals WHERE referral_code = %s;",
            (referral_code,)
        )

        entry = cur.fetchone()
        if entry is None:
            raise APIError(APIError.INTERNAL, "Referral code not found")

        return entry[0], entry[1]

    @staticmethod
    def apply_referral_code(creator_id: uuid.UUID, referral_code: str, cur: cursor) -> uuid.UUID:
        referral_code = check_referral_code(referral_code)

        # Create referral code for referree just in case it does not exist
        Referrals.get_referral_code(creator_id, cur)
        referral_id, referred_by = Referrals.get_referral_id(referral_code, cur)
        if creator_id == referral_id:
            raise APIError(APIError.INTERNAL, "You can not refer to yourself")

        if creator_id == referred_by:
            raise APIError(APIError.INTERNAL, "You have already been referred by this user")

        cur.execute(
            "UPDATE public.referrals "
            "SET referred_by = %s, referred_at = (now() at time zone 'utc') "
            "WHERE creator_id = %s AND referred_by IS NULL "
            "RETURNING creator_id;",
            (referral_id, creator_id)
        )

        entry = cur.fetchone()
        if entry is None:
            raise APIError(APIError.INTERNAL, "Referral code was already applied")

        return referral_id
